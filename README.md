# 晒图魔方

本地图片整理工具，用于电商图片分类、重复识别和人工筛选。

## 功能

- 扫描本地图片文件夹，支持 jpg、png、bmp、webp
- 识别完全重复、文件名副本、视觉相似图片
- 自动生成缩略图、质量分和处理候选
- 支持复制“处理候选”和“保留建议”到输出文件夹
- 支持导出 CSV 表格
- 默认不删除、不移动原图

## 启动

```powershell
cd C:\Users\云电脑\image-cube
python -m uvicorn app.main:app --host 127.0.0.1 --port 18130
```

打开：

```text
http://127.0.0.1:18130
```

## 默认扫描目录

```text
C:\Users\云电脑\Desktop\白底图\外贸绞肉机图
```

## 打包 EXE

```powershell
cd C:\Users\云电脑\image-cube
.\build-exe.ps1
```

生成位置：

```text
C:\Users\云电脑\image-cube\dist\晒图魔方\晒图魔方.exe
```

## 原则

- 不删除原图
- 不移动原图
- 只生成本地数据库、缩略图和筛选报告
