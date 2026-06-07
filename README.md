# 筛图魔术盒

面向摄影师、电商修图和批量素材整理的 Windows 本地筛图工具。它可以扫描图片文件夹，识别重复/相似图片，自动给出初筛分类，并把去重后的保留图导出到指定目录。

<p align="center">
  <img src="docs/screenshots/main-window.png" alt="筛图魔术盒主界面" width="920">
</p>

<p align="center">
  <a href="https://github.com/xiaokaige1130-maker/saitu-magic-box/releases/latest">
    <img alt="下载 Windows 安装包" src="https://img.shields.io/badge/下载-Windows%20x64-11a77a?style=for-the-badge">
  </a>
  <img alt="本地运行" src="https://img.shields.io/badge/运行方式-本地处理-334155?style=for-the-badge">
  <img alt="平台" src="https://img.shields.io/badge/平台-Windows-2563eb?style=for-the-badge">
</p>

## 下载安装

直接下载：[SaituMagicBox-v1.0.0-Windows-x64.zip](https://github.com/xiaokaige1130-maker/saitu-magic-box/releases/latest/download/SaituMagicBox-v1.0.0-Windows-x64.zip)。

也可以打开 [Releases 下载页](https://github.com/xiaokaige1130-maker/saitu-magic-box/releases/latest)，下载最新的 Windows x64 发布包。

1. 解压 ZIP 文件。
2. 双击 `筛图魔术盒.exe` 启动。
3. 选择原图文件夹和输出文件夹，点击 `开始筛选`。

> 当前发布包是绿色版 Windows 程序，无需安装，不写入系统目录。

## 核心功能

- 扫描本地图片文件夹，支持 jpg、jpeg、png、bmp、webp、tif、tiff 等常见格式。
- 识别完全重复、文件名副本、视觉相似图片。
- 自动生成缩略图、质量分、清晰度、曝光、反差、饱和度指标。
- 自动分类为 `精选`、`较差`、`空镜`、`废片`，并生成问题标签。
- `重复去重` 视图只展示每个重复/相似组里系统判断最好的那一张。
- 支持导出勾选图片、导出当前视图、导出去重后全部、按分类导出。
- 默认只复制图片，不删除、不移动原图。

## 使用说明

| 操作 | 说明 |
| --- | --- |
| `开始筛选` | 扫描原图文件夹并自动分类 |
| `全选当前` / `清空勾选` | 管理当前列表的勾选状态 |
| `重复去重` | 每组重复/相似图片只保留最佳候选 |
| `勾选去重` | 勾选当前去重结果，或在其它视图勾选全库去重后的保留图 |
| `导出勾选` | 只复制已勾选图片 |
| `去重后全部` | 全库去重后导出，唯一图片也会保留 |
| `导出当前` | 复制当前视图内的图片 |
| `分类导出` | 按精选、较差、空镜、废片分别复制 |
| 双击缩略图 | 打开原图查看 |

## 数据安全

- 所有扫描、评分、去重都在本机完成。
- 程序不会上传图片。
- 导出时使用复制方式，不会删除或移动原图。
- 本地数据库和缩略图保存在程序目录下的 `data` 文件夹中。

## 开发运行

```powershell
git clone https://github.com/xiaokaige1130-maker/saitu-magic-box.git
cd saitu-magic-box
python -m pip install -r requirements.txt
python launcher.py
```

## 打包 Windows 程序

```powershell
.\build-exe.ps1
```

打包完成后，程序位于：

```text
dist\筛图魔术盒\筛图魔术盒.exe
```

## RAW 文件说明

代码已经识别 cr2、cr3、nef、arw、raf、dng 扩展名。当前默认依赖不强制安装 `rawpy`，因此没有 RAW 解码环境时这些文件会显示在扫描失败列表里；安装可用的 `rawpy` 后会自动读取 RAW 预览。

## 开源许可

本项目基于 MIT License 开源。
