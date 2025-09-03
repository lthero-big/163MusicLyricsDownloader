#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
Batch fetch Netease Cloud Music lyrics (lrc + tlyric) by:
- Song IDs
- Song URLs
- "Song Name - Artist" queries (fuzzy matched via search API)

Outputs per-song folder with raw.lrc, trans.lrc, merged.lrc and
summary.csv (all songs), resolved.csv (query-to-song mapping).

Python 3.8+ ; pip install requests
"""

import argparse
import csv
import json
import os
import re
import time
from pathlib import Path
from typing import Dict, List, Optional, Tuple

import requests
from difflib import SequenceMatcher

# --- Constants

UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/124.0 Safari/537.36"
)

HEADERS = {
    "User-Agent": UA,
    "Referer": "https://music.163.com/",
    # 替换成自己账号的Cookie
    "Cookie": "os=pc; appver=2.9.7;",
}

DETAIL_URL = "https://music.163.com/api/song/detail/?ids=[{}]"
LYRIC_URL = "https://music.163.com/api/song/lyric?id={}&lv=1&kv=1&tv=1"
SEARCH_URL = "https://music.163.com/api/search/pc"  # GET s=keyword&offset=0&limit=N&type=1

ID_IN_URL = re.compile(r"[?&]id=(\d+)")
TIMESTAMP = re.compile(r"\[(\d{2}):(\d{2})(?:\.(\d{1,3}))?\]")

# --- Utilities

def ensure_dir(p: Path) -> None:
    p.mkdir(parents=True, exist_ok=True)

def normalize_text(s: str) -> str:
    # 统一大小写，去掉空白与标点，用于模糊匹配
    s = s.lower().strip()
    s = re.sub(r"[^\w\u4e00-\u9fff]+", "", s)  # 保留字母数字与中日韩统一表意文字
    return s

def seq_ratio(a: str, b: str) -> float:
    return SequenceMatcher(a=normalize_text(a), b=normalize_text(b)).ratio()

def parse_ids_from_text_line(line: str) -> Optional[str]:
    """
    Return a song ID if the line is a pure ID or a Netease URL containing ?id=.
    Otherwise return None (could be a name-artist query).
    """
    line = line.strip()
    if not line:
        return None
    m = ID_IN_URL.search(line)
    if m:
        return m.group(1)
    if line.isdigit():
        return line
    return None

def parse_name_artist_query(line: str) -> Optional[Tuple[str, Optional[str]]]:
    """
    Parse 'Song - Artist' (dash can have surrounding spaces). Also accept only 'Song' (without artist).
    Returns (name, artist or None). If not a plausible query, return None.
    """
    line = line.strip()
    if not line:
        return None
    # 常见分隔符：-、—、–，尽量兼容
    parts = re.split(r"\s*[-–—]\s*", line, maxsplit=1)
    if len(parts) == 2 and parts[0] and parts[1]:
        return parts[0].strip(), parts[1].strip()
    # 没有歌手也允许用歌名搜索
    # 排除已被解析成ID/URL的情况（在上层调用里会先尝试ID/URL解析）
    if not line.isdigit() and "http" not in line.lower():
        return (line, None)
    return None

def ms_from_tag(tag: str) -> int:
    m = TIMESTAMP.match(tag)
    if not m:
        return -1
    mm = int(m.group(1))
    ss = int(m.group(2))
    xxx = m.group(3)
    ms = int((xxx or "0").ljust(3, "0")[:3])
    return (mm * 60 + ss) * 1000 + ms

def parse_lrc_to_map(lrc: str) -> Dict[int, str]:
    out: Dict[int, str] = {}
    for raw_line in lrc.splitlines():
        if not raw_line.strip():
            continue
        tags = TIMESTAMP.findall(raw_line)
        if not tags:
            continue
        text = TIMESTAMP.sub("", raw_line).strip()
        for tag in TIMESTAMP.finditer(raw_line):
            ts_ms = ms_from_tag(tag.group(0))
            if ts_ms >= 0:
                out[ts_ms] = text
    return out

def merge_lrc(base_map: Dict[int, str], trans_map: Dict[int, str]) -> List[str]:
    if not base_map:
        return []
    merged_lines = []
    trans_keys = sorted(trans_map.keys())

    def find_near(ms: int, tol: int = 500) -> Optional[str]:
        import bisect
        i = bisect.bisect_left(trans_keys, ms)
        candidates = []
        if i < len(trans_keys):
            candidates.append(trans_keys[i])
        if i > 0:
            candidates.append(trans_keys[i-1])
        best = None
        best_d = tol + 1
        for k in candidates:
            d = abs(k - ms)
            if d <= tol and d < best_d:
                best, best_d = k, d
        return trans_map.get(best) if best is not None else None

    for ts in sorted(base_map.keys()):
        tag = ts_to_tag(ts)
        base_text = base_map[ts]
        trans_text = find_near(ts) if trans_map else None
        if trans_text:
            merged_lines.append(f"{tag}{base_text} / {trans_text}")
        else:
            merged_lines.append(f"{tag}{base_text}")
    return merged_lines

def ts_to_tag(ms: int) -> str:
    mm = ms // 60000
    ss = (ms % 60000) // 1000
    xxx = ms % 1000
    return f"[{mm:02d}:{ss:02d}.{xxx:03d}]"

def safe_filename(name: str) -> str:
    return re.sub(r'[\\/:*?"<>|]+', "_", name).strip() or "unknown"

# --- NetEase API helpers

def get_song_detail(session: requests.Session, song_id: str, retries: int = 2, sleep: float = 0.6) -> Tuple[str, str]:
    url = DETAIL_URL.format(song_id)
    for _ in range(max(1, retries + 1)):
        try:
            r = session.get(url, headers=HEADERS, timeout=10)
            if r.status_code == 200:
                data = r.json()
                songs = (data or {}).get("songs") or []
                if songs:
                    s0 = songs[0]
                    name = s0.get("name") or ""
                    artists = s0.get("artists") or []
                    artist_str = " & ".join(a.get("name", "") for a in artists if a)
                    return name, artist_str
        except Exception:
            pass
        time.sleep(sleep)
    return "", ""

def get_song_lyrics(session: requests.Session, song_id: str, retries: int = 2, sleep: float = 0.6) -> Tuple[str, str]:
    url = LYRIC_URL.format(song_id)
    for _ in range(max(1, retries + 1)):
        try:
            r = session.get(url, headers=HEADERS, timeout=10)
            if r.status_code == 200:
                data = r.json()
                lrc = ((data or {}).get("lrc") or {}).get("lyric") or ""
                tlyric = ((data or {}).get("tlyric") or {}).get("lyric") or ""
                return lrc.strip(), tlyric.strip()
        except Exception:
            pass
        time.sleep(sleep)
    return "", ""

def search_song(session: requests.Session, name: str, artist: Optional[str], limit: int = 10, retries: int = 2, sleep: float = 0.6, fuzzy: bool = True) -> Optional[str]:
    """
    Use the public PC search API to find a song ID by name (and optional artist).
    Return best-matched song ID or None.
    """
    params = {"s": f"{name} {artist or ''}".strip(), "type": 1, "offset": 0, "limit": limit}
    for _ in range(max(1, retries + 1)):
        try:
            r = session.get(SEARCH_URL, headers=HEADERS, params=params, timeout=10)
            if r.status_code == 200:
                data = r.json()
                result = (data or {}).get("result") or {}
                songs = result.get("songs") or []
                if not songs:
                    return None
                # Score candidates
                best_id = None
                best_score = -1.0
                for s in songs:
                    sid = str(s.get("id", "")).strip()
                    sname = s.get("name") or ""
                    s_artists = " & ".join(a.get("name", "") for a in (s.get("artists") or []) if a) or ""
                    # 基础分：歌名相似度
                    score = seq_ratio(name, sname) * 100
                    # 加权：歌手命中加分
                    if artist:
                        if normalize_text(artist) in normalize_text(s_artists):
                            score += 20
                        else:
                            # 宽松：任一候选歌手与输入歌手相似
                            art_parts = re.split(r"[,&/、和+ ]+", s_artists)
                            if any(seq_ratio(artist, ap) >= 0.7 for ap in art_parts if ap.strip()):
                                score += 10
                            elif not fuzzy:
                                # 非宽松模式下，歌手不匹配则降权
                                score -= 10
                    # 轻微加成：完全同名
                    if normalize_text(name) == normalize_text(sname):
                        score += 5
                    if score > best_score:
                        best_score = score
                        best_id = sid
                return best_id
        except Exception:
            pass
        time.sleep(sleep)
    return None

# --- IO

def read_entries(args) -> List[str]:
    """
    Read mixed inputs from:
    - --inputs (comma-separated)
    - --input (file, one per line)
    Returns a list of raw entries (strings), preserving order and de-duplicated later.
    """
    entries: List[str] = []
    if args.inputs:
        for part in args.inputs.split(","):
            if part.strip():
                entries.append(part.strip())
    if args.input:
        with open(args.input, "r", encoding="utf-8") as f:
            for line in f:
                if line.strip():
                    entries.append(line.strip())
    # de-dup while preserving order
    seen = set()
    ordered = []
    for x in entries:
        if x not in seen:
            seen.add(x)
            ordered.append(x)
    return ordered

# --- Main

def main():
    parser = argparse.ArgumentParser(description="Batch fetch Netease Cloud Music lyrics.")
    parser.add_argument("--inputs", help="Comma-separated entries: ID, URL, or 'Song - Artist'.", default="")
    parser.add_argument("--input", help="Text file with one entry per line (ID/URL/'Song - Artist').", default="")
    parser.add_argument("--outdir", help="Output directory.", default="./lyrics")
    parser.add_argument("--sleep", type=float, default=0.6, help="Sleep seconds between requests.")
    parser.add_argument("--retries", type=int, default=2, help="Retry times on failure.")
    parser.add_argument("--search-limit", type=int, default=10, help="Max search candidates for name-artist queries.")
    parser.add_argument("--fuzzy", action="store_true", default=True, help="Enable fuzzy matching for artist/name.")
    parser.add_argument("--no-fuzzy", dest="fuzzy", action="store_false", help="Disable fuzzy matching.")
    args = parser.parse_args()

    raw_entries = read_entries(args)
    if not raw_entries:
        print("No valid entries found. Use --inputs or --input.")
        return

    outdir = Path(args.outdir)
    ensure_dir(outdir)

    session = requests.Session()

    # Writers
    summary_path = outdir / "summary.csv"
    resolved_path = outdir / "resolved.csv"
    sum_f = open(summary_path, "w", newline="", encoding="utf-8-sig")
    res_f = open(resolved_path, "w", newline="", encoding="utf-8-sig")
    sum_writer = csv.writer(sum_f)
    res_writer = csv.writer(res_f)
    sum_writer.writerow(["song_id", "name", "artists", "has_lrc", "has_tlyric", "folder"])
    res_writer.writerow(["original_query", "resolved_song_id", "resolved_name", "resolved_artists", "match_note_or_score"])

    try:
        for idx, entry in enumerate(raw_entries, 1):
            print(f"[{idx}/{len(raw_entries)}] Resolving: {entry}")

            # 1) 先尝试ID/URL
            sid = parse_ids_from_text_line(entry)
            name_q, artist_q = None, None
            match_note = ""

            # 2) 若不是ID/URL，则尝试解析“歌名-歌手”或仅歌名
            if not sid:
                na = parse_name_artist_query(entry)
                if na:
                    name_q, artist_q = na
                    sid = search_song(
                        session,
                        name=name_q,
                        artist=artist_q,
                        limit=args.search_limit,
                        retries=args.retries,
                        sleep=args.sleep,
                        fuzzy=args.fuzzy,
                    )
                    match_note = f"by_search:{name_q} | {artist_q or ''}"
                else:
                    match_note = "unrecognized_entry"

            if not sid:
                print(f"  !! Unable to resolve entry: {entry}")
                res_writer.writerow([entry, "", "", "", "unresolved"])
                time.sleep(args.sleep)
                continue

            # 抓取元数据与歌词
            s_name, s_artists = get_song_detail(session, sid, retries=args.retries, sleep=args.sleep)
            lrc, tlyric = get_song_lyrics(session, sid, retries=args.retries, sleep=args.sleep)

            folder_name = f"{sid} - {safe_filename(s_name or 'unknown')}"
            song_dir = outdir / folder_name
            ensure_dir(song_dir)

            has_lrc = bool(lrc)
            has_tlyric = bool(tlyric)

            if has_lrc:
                (song_dir / "raw.lrc").write_text(lrc, encoding="utf-8")
            if has_tlyric:
                (song_dir / "trans.lrc").write_text(tlyric, encoding="utf-8")

            # 合并
            try:
                base_map = parse_lrc_to_map(lrc) if has_lrc else {}
                trans_map = parse_lrc_to_map(tlyric) if has_tlyric else {}
                if base_map:
                    merged_lines = merge_lrc(base_map, trans_map)
                    if merged_lines:
                        (song_dir / "merged.lrc").write_text("\n".join(merged_lines), encoding="utf-8")
            except Exception as e:
                print(f"  Merge warning for {sid}: {e}")

            sum_writer.writerow([sid, s_name, s_artists, int(has_lrc), int(has_tlyric), str(song_dir)])
            res_writer.writerow([entry, sid, s_name, s_artists, match_note or "id_or_url"])
            time.sleep(args.sleep)
    finally:
        sum_f.close()
        res_f.close()

    print(f"Done.\nSummary: {summary_path}\nResolved: {resolved_path}")

if __name__ == "__main__":
    main()
