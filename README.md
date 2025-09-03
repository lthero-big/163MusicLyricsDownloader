# 网易云音乐歌词批量下载器

# 配置方式
1、访问网易云音乐web端，登录自己的账号

2、按F12，找到“网络”->“music.163.com”文件->“标头”->Cookie
<img width="918" height="529" alt="image" src="https://github.com/user-attachments/assets/ca0f9e11-c31b-47f3-a3c4-31ba26896cab" />

3、将Cookie的值全部复制，并填写在fetch163Lyrics.py里的Cookie值
```
"Cookie": "os=pc; appver=2.9.7;",
```
将`os=pc; appver=2.9.7;`替换成复制的Cookie内容，保存文件即可


# 使用方式

## 方式A：一次性混合输入（ID、URL、或“歌名 - 歌手”）
```
python fetch163Lyrics.py \
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
python fetch163Lyrics.py --input lines.txt
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
python fetch163Lyrics.py --input lines.txt --outdir ./lyrics --search-limit 15 --fuzzy
```
