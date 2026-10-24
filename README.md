# Eng_Zh translator

*A self-use translator to aid essay reading.*

把英文 PDF 翻成中英对照（或纯中文）的译文 PDF。**完全本地运行**：模型跑在你自己的
机器上，不联网、不上传、不花钱。为读大量英文文献而做——尤其是那些排版复杂的
学术期刊和扫描自纸质书的电子版。

- **逐句翻译，不会瞎编**：用 Helsinki-NLP 的 `opus-mt-en-zh`（Marian NMT）。它一次只看
  一个句子，没有"自由发挥"的空间——不会跳译、不会脑补、不会把一整段压缩成一句。
  代价是文笔比大模型硬，但意思是稳的。
- **中英对照排版**：中文在上、英文原文在下（灰色小字），标出「原文 第 N 页」，
  读到可疑处能立刻核对。
- **认得懂版面**：单栏的书、双栏的论文、三栏的杂志，页面中间横插通栏图表的也行。

## 快速开始

需要 **Python 3.10–3.12**（依赖里的 torch 2.2 没有 3.13 及以上的安装包，安装脚本会先检查版本）。

**Windows**：双击 `install.bat` → 双击 `run.bat`
**macOS / Linux**：`bash install.command` → `bash run.command`

浏览器会自动打开 `http://127.0.0.1:8765`，把 PDF 拖进去即可。出问题运行
`check.bat` / `bash check.command` 自检，它会逐项告诉你哪坏了、怎么修。

> macOS 上双击 `.command` 没反应，是文件从别的系统拷过来丢了可执行权限：
> 终端里 `chmod +x *.command`，或者直接用 `bash xxx.command` 运行。

## 界面上的选项

| 选项 | 说明 |
| --- | --- |
| 输出 | 中英对照 / 只要中文 |
| 质量 | 标准（beam=4，更准）/ 快速（beam=1，快 2–3 倍）|
| 页码范围 | 只翻某几页。**整本书建议先试译 5 页**，确认版面没问题再跑全书 |
| 跳过参考文献 | 跳过 References / Literature Cited / Bibliography 部分，遇到附录或补充材料时恢复，省时间 |

速度约 3–8 句/秒（普通 CPU）。一篇 20 页论文几分钟，一本 300 页的书放着跑几小时，
多个文件会自动排队。翻过的句子存在 `cache.db`，重复内容不重算。

## 文件去哪了

上传的原文和生成的译文**只写在系统临时目录**：原文翻完立刻删除，译文要等你点
「下载」才由浏览器存进下载目录，程序退出时临时目录整个清空（万一异常退出，
下次启动会清掉 24 小时前的残留）。项目文件夹里不会堆积任何东西。

唯一会留下的是 `cache.db` —— 翻过的句子存在里面，重翻同一本书时能省不少时间。
它会留下你翻译过的文本，介意的话删掉即可，或者启动前设 `MT_CACHE=off` 关掉。

## 版面处理

这是整个项目最麻烦的部分，`pdf_extract.py` 里做了这些事：

- **分栏**：以 pdfminer 的"文本框"为单位（这种框天然不跨栏），再用矩形级的
  **XY-cut**（先竖切分栏、切不动再横切分带）递归排出阅读顺序。页面中间横插一张
  带文字标签的通栏图——这种最容易让人栽跟头的版面——也能正确还原。
- **参考文献角标**：`recognition1–4` 里的上标数字按"字号更小 + 基线抬高"识别并剔除。
  不处理的话翻译模型会被这些数字带偏，吐出一长串数字乱码。
- **页眉页脚页码**：只在页面上下边缘带里识别（页码模式、全大写不加粗的短行），再加上
  跨页重复检测（同一行文字去掉页码后在多页的边缘出现）。正文里全大写的小节标题
  （INTRODUCTION、REFERENCES）和段落末尾的短行（"it."）不会被误删。
- **脚注上标**：比正文小的纯数字行会被剔除，否则会把段落从中间劈开。
- **断行与连字符**：`un-` + `naturalness` 还原成 `unnaturalness`。
- **跨页跨栏续段**：上一段确实没写完、且下一段以小写开头，才接回去——
  宁可多切一刀，也不把整页文字错误地塞进上一段。跨页合并的段落记录起止页
  （`page` / `page_end`）。
- **页码约定**：所有页码都是 PDF 的物理页序（文件里第 1 页就是 1），不是期刊印刷的页码。
- **小节标签**：每个文本块带 `section`（所在小节标题），参考文献部分标为 `References`，
  其他程序复用 `pdf_extract.py` 时可以按小节过滤。
- **字符规范化**：`ﬁ`/`ﬂ` 连字还原成 `fi`/`fl`（否则英文原文会显示成黑方块，
  模型也不认识），`(cid:123)` 之类的残留一并清掉。

两个解析后端：**pdfminer.six**（主力，几何精确）和 **pypdf**（纯 Python 零原生依赖的
兜底，老系统上装不了 pdfminer 时用）。自检脚本会告诉你实际用的是哪个。

## 中文字体

自动在系统里找一个**真的带汉字字形**的 TrueType 字体（Windows 的微软雅黑/宋体、
macOS 的 STHeiti/Songti/Arial Unicode），找不到就整目录扫。苹方 PingFang 和思源系列是
PostScript 轮廓，ReportLab 用不了，会被自动跳过——这是正常的。都没有就退回 PDF
内置中文字体。想指定字体：把任意中文 `.ttf`/`.ttc` 丢进 `fonts/`。

## 测试

```
pip install -r requirements-dev.txt
python -m pytest
```

测试用 ReportLab 现场生成双栏论文、通栏插图、跨页段落等合成 PDF，检查版面还原，
不需要模型、不联网，几秒跑完。

## 常见问题

| 症状 | 原因与对策 |
| --- | --- |
| `WinError 1114 ... c10.dll` | 装过 Anaconda 的机器上，它的 `libiomp5md.dll` 和 torch 自带的撞车。启动脚本里已设 `KMP_DUPLICATE_LIB_OK=TRUE`；仍不行就按 `requirements.txt` 用 `torch<2.3` + `numpy<2` |
| 进程无声退出、网页进度条不动 | 多半是某个 C 扩展加载即崩（常见 sentencepiece）。`pip install --force-reinstall --no-cache-dir sentencepiece` |
| `CVE-2025-32434` / 拒绝读 `.bin` | 新版 transformers 不让 `torch<2.6` 读 `.bin` 权重。换 safetensors 格式的权重，或按 requirements 把 transformers 降到 `<4.42` |
| 卡在"下载模型" | `python download_model.py` —— 它会测连通性、逐文件下载、失败自动退回直连 HTTP，还支持 `--proxy 7890` |
| 中文显示成方块 | 往 `fonts/` 里放一个中文字体文件 |
| 扫描件译不出来 | 纯图片 PDF 没有文字层，需要先做 OCR，本项目不含 OCR |

## 模型

首次运行会自动把 `Helsinki-NLP/opus-mt-en-zh`（约 310MB）下到 `model/` 文件夹，
之后完全离线。也可以手动下载 `config.json`、`pytorch_model.bin`、`source.spm`、
`target.spm`、`tokenizer_config.json`、`vocab.json` 放进 `model/`，程序会自动认出来。

想换模型：设环境变量 `MT_MODEL` 为别的 Marian 模型名或本地路径。

## 代码结构

```
app.py                   Flask 服务端 + 任务队列 + 临时文件生命周期
pipeline.py              主流程：PDF → 段落 → 句子 → 译文 → 新 PDF
pdf_extract.py           版面还原（分栏、页眉页脚、角标、合段），两个后端共用
pdf_extract_pdfminer.py  pdfminer 后端：文本框 + 精确字号坐标
pdf_extract_pypdf.py     pypdf 后端：纯 Python 兜底
segment.py               英文分句（处理 e.g. / Fig. / 人名缩写等）
translate_engine.py      Marian 翻译引擎 + SQLite 缓存 + 退化检测
pdf_render.py            ReportLab 排版生成对照 PDF
selftest.py              自检 + 常见故障对策
tests/                   pytest 回归测试（合成 PDF，不需要模型）
download_model.py        模型下载（多源、可代理、可直连）
templates/index.html     网页界面（单文件，无前端依赖）
```

## 说明

自用项目，没有附加开源许可。

翻译模型 `Helsinki-NLP/opus-mt-en-zh` 来自 Helsinki-NLP 的 OPUS-MT 项目，遵循它自己的
许可（Apache-2.0），本仓库不包含模型文件，运行时按需下载。译文质量由模型决定，
关键结论请对照英文原文。
