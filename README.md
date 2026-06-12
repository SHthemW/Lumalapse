# Lumalapse

类似 LRTimelapse 的延时摄影后期工具:导入 RAW 序列 → 预览曝光曲线 → 关键帧调色 → 去闪 → 导出视频。
支持 **CLI** 与 **GUI** 双界面。

## 功能

- **RAW 序列导入**:基于 LibRaw(rawpy),支持 ARW / CR2 / CR3 / NEF / DNG / RAF / ORF / RW2 等;也支持 JPEG/TIFF 序列
- **曝光曲线**:逐帧计算线性光 log2 亮度曲线,并从 EXIF 读取相机 EV(快门/光圈/ISO)曲线
- **关键帧调色**:在任意帧设置 曝光 / 高光 / 阴影 / 白色色阶 / 黑色色阶 / 对比度 / 饱和度 / 去雾(暗通道先验)/ 色温,帧间平滑插值
- **基于曝光的去闪**:解析式(对亮度曲线高斯平滑,差值作逐帧 EV 补偿,保留有意的渐变)
  与**视觉式**(渲染小尺寸成品并实测亮度,迭代收敛——LRTimelapse 同思路,任何引擎/闪烁类型都精确;
  `deflicker --visual` 或 GUI「计算视觉去闪」)
- **圣杯模式**:日转夜拍摄中相机阶梯调整快门/ISO 造成的亮度跳变,依据 EXIF EV 曲线自动补偿抹平
  (`lumalapse holygrail` 或 GUI 复选框)
- **DCP 相机色彩档**:RawTherapee 引擎自动匹配相机专属 DCP 校准(色相/饱和度查找表、
  相机色调曲线、baseline exposure——与 Adobe Camera Raw 同机制);
  可用环境变量 `LUMALAPSE_DCP` 强制指定 .dcp 文件(如 Adobe DNG Converter 提供的档案)
- **视频导出**:内置 ffmpeg(imageio-ffmpeg),支持 H.264 / H.265 / ProRes
- **双渲染引擎**:`builtin`(numpy,快速、实时预览)与 `rawtherapee`(通过
  rawtherapee-cli 调用 [RawTherapee](https://rawtherapee.com) 的成熟 RAW 管线:
  专业色彩科学、高光重建、RT 去雾;参数自动映射为 PP3 处理配置文件)。
  GUI 右侧面板或 `lumalapse engine <项目> rawtherapee` 切换,
  `lumalapse export --engine rawtherapee` 可单次覆盖

## 安装

```bash
pip install -e .
```

需要 Python ≥ 3.10。Windows / macOS / Linux 均可。

## GUI 用法

```bash
lumalapse gui                # 空白启动
lumalapse gui <文件夹或项目>  # 直接打开
```

1. `文件 → 打开图片文件夹`,自动分析曝光曲线(蓝线 = 原始亮度,橙线 = 调整后);
   分析结果与关键帧自动存入 `<文件夹>/.lumalapse/`,再次打开同一文件夹秒开
2. 拖动绿色播放头或底部滑块定位帧;右侧面板修改参数即在当前帧创建/更新关键帧(红色菱形)
3. 勾选「启用基于曝光的去闪」,调整平滑强度,曲线和预览实时更新
4. `导出视频…` 设置帧率/分辨率/编码后导出

## CLI 用法

```bash
# 1. 分析序列,结果缓存在 <folder>/.lumalapse/project.llproj,打印曝光曲线 sparkline
#    再次 analyze 或 GUI 打开同一文件夹会直接复用缓存(--force 强制重新分析)
lumalapse analyze D:\timelapse\shot01

# 2. 查看曲线 / 导出 CSV
lumalapse curve D:\timelapse\shot01 --csv curve.csv

# 3. 设置关键帧(帧号 0 和 299)
lumalapse keyframe set D:\timelapse\shot01 0   --exposure 0.5 --saturation 1.1 --dehaze 0.3
lumalapse keyframe set D:\timelapse\shot01 299 --exposure -0.5
lumalapse keyframe list D:\timelapse\shot01

# 4. 启用去闪
lumalapse deflicker D:\timelapse\shot01 --enable --strength 12

# 5. 导出视频
lumalapse export D:\timelapse\shot01 -o out.mp4 --fps 25 --width 3840 --codec h264 --quality 16

# 或者两段式(LRTimelapse 风格):先冲洗成 JPG/TIFF 序列,检查/修图后再合成
lumalapse render D:\timelapse\shot01 -o D:\timelapse\developed --format jpg --quality 95
lumalapse assemble D:\timelapse\developed -o out.mp4 --fps 25
```

`--half-size` 可让 RAW 以半分辨率解拜耳,速度提升约 4 倍,适合预览版导出。

## 与 Adobe Camera Raw / Lightroom 的对照

使用 RawTherapee 引擎时,各冲洗环节与 ACR 的机制对应关系:

| 环节 | Adobe Camera Raw | Lumalapse(RawTherapee 引擎) | 状态 |
|---|---|---|---|
| 相机色彩校准 | 相机专属 DCP(色相/饱和度查找表、相机色调曲线、baseline exposure) | 自动匹配 RT 内置 DCP;**装有 Adobe DNG Converter / Camera Raw 时自动改用 Adobe Standard DCP(Adobe 官方校准数据)**;`LUMALAPSE_DCP` 可强制指定 | ✅ 同机制,可用 Adobe 官方数据 |
| 高光重建 | 用未饱和通道重建已饱和通道 | RT 色彩传播重建(HLRecovery/Coloropp) | ✅ 等效 |
| 曝光 | 线性增益 | PP3 Compensation(线性增益) | ✅ 同构 |
| 高光/阴影(恢复方向) | PV2012 局部自适应、防光晕 | RT Shadows&Highlights:空间局部、边缘感知 guided filter 防光晕 | ✅ 等效机制 |
| 白色/黑色色阶、高光/阴影(增强方向) | 参数化色调曲线 | PP3 自定义对角曲线 | ✅ 同构 |
| 去雾 | Dehaze | RT Haze Removal | ✅ 等效 |
| 默认捕捉锐化 | 默认开启(锐化 40) | RT PostDemosaicSharpening 默认开启 | ✅ 对齐 |
| 逐像素一致 | — | — | ❌ 不追求:PV2012 内部算法与 Adobe 色彩引擎为专有实现,任何第三方都无法逐像素复刻 |

> 内置(numpy)引擎的高光/阴影为全局亮度遮罩,实时性好但无局部自适应;追求 Adobe 级冲洗质量时请切换 RawTherapee 引擎。

## 工作原理

- RAW 以线性 gamma、固定相机白平衡、关闭自动增亮解码,因此曝光调整是**精确的线性增益**
- 色调管线在**未裁剪的线性数据**上运行:曝光推高后超过 1.0 的数据不会立即丢弃,
  高光(亮度遮罩增益)与白色色阶(白点电平)可以把过冲拉回显示范围,真正利用 RAW 的高光余量
- 亮度统计使用 log2 域均值:+1 EV 恰好使曲线上移 1.0,去闪补偿无需迭代重渲染
- 去闪 = 高斯平滑后的目标曲线 − 实测曲线,叠加在关键帧曝光之上,保留人为渐变
- 去雾使用暗通道先验 + 边缘保持滤波细化透射图

## 项目结构

```
lumalapse/
├── loader.py       RAW/图像解码 + EXIF
├── analysis.py     曝光曲线分析
├── keyframes.py    关键帧与插值
├── adjustments.py  曝光/饱和度/去雾/对比度/色温
├── deflicker.py    去闪算法
├── project.py      项目模型(JSON 持久化)
├── render.py       渲染管线
├── export.py       ffmpeg 视频导出
├── cli.py          命令行界面
└── gui/            PySide6 + pyqtgraph 图形界面
```
