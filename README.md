# 网易云音乐歌词批量下载器

# 使用方式

## 方式A：一次性混合输入（ID、URL、或“歌名 - 歌手”）
```
python fetch_163_lyrics.py \
  --inputs "208902,https://music.163.com/#/song?id=1330348068,那些花儿 - 朴树, 体面-于文文"
```

## 方式B：从文本文件批量读取（每行一个，三种格式可混用）
例：lines.txt 包含以下内容

> https://music.163.com/#/song?id=208902
> 
> 33894312
> 
> 那些花儿 - 朴树
> 
> 体面-于文文

```
python fetch_163_lyrics.py --input lines.txt
```

## 可选参数
> --outdir 输出目录（默认 ./lyrics）
> 
> --sleep  每首间隔秒数（默认 0.6）
> 
> --retries 重试（默认 2）
> 
> --search-limit 搜索候选数（默认 10）
> 
> --fuzzy  开启更宽松匹配（默认开）

```
python fetch_163_lyrics.py --input lines.txt --outdir ./lyrics --search-limit 15 --fuzzy
```
