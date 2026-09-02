# Cercus 启动指南

## 正常启动（图形桌面环境）

在 Windows 图形桌面环境中（不是 SSH 或远程终端）：

```bash
conda activate psychopy
cd D:/Projects/Cercus
python main.py
```

**预期行为：**
- 控制台打印 `Dashboard token: ...` 和 `Monitor available at: ...`
- NiceGUI 打印 `ready to go on http://localhost:8000 ...`
- **自动打开本地窗口**（WebView2 native window）显示 Dashboard

**如果没有自动打开窗口：**
- 手动访问 `http://localhost:8000/monitor`（只读监控页面）
- 或等待几秒，WebView2 初始化需要时间

## 无头环境/SSH 测试

如果在 SSH 或无图形环境中测试：

```bash
cd D:/Projects/Cercus
python test_server.py
```

**预期输出：**
```
NiceGUI ready to go on http://127.0.0.1:8765
[OK] Server responded: HTTP 200
[OK] /monitor page rendered successfully
```

这验证了服务器逻辑正常，只是没有图形窗口。

## 常见问题

### 1. `TypeError: Config.__init__() got an unexpected keyword argument 'native_url'`

**原因：** 旧版本代码使用了不存在的参数。  
**修复：** 已在 commit `2a6fb07` 修复，确保代码是最新的：
```bash
git pull origin main
```

### 2. `[Errno 10048] ... 端口已被占用`

**原因：** 之前的进程仍在运行。  
**修复：**
```bash
# 查找占用端口的进程
netstat -ano | findstr :8000

# 杀死进程（替换 <PID> 为实际 PID）
taskkill /F /PID <PID>
```

### 3. `WebView2 initialization failed: 无效的窗口句柄`

**原因：** 
- 在 SSH/无头环境中运行（正常，服务器仍然可用）
- 或 WebView2 Runtime 未安装

**解决：**
- SSH 环境：忽略此错误，使用浏览器访问 `http://localhost:8000/monitor`
- 桌面环境：安装 [WebView2 Runtime](https://developer.microsoft.com/en-us/microsoft-edge/webview2/)

### 4. Native 窗口无法访问 /dashboard

**正常行为：** `/dashboard` 页面被 token 保护，只有 native 窗口知道 token。浏览器直接访问会显示 "Access denied"。

**监控访问：** 使用 `/monitor` 页面（只读，无需 token）。

## 验证检查表

运行以下命令验证环境：

```bash
# 1. 检查 Python 版本
conda activate psychopy
python --version  # 应该是 Python 3.10.x

# 2. 检查 NiceGUI 安装
python -c "import nicegui; print(nicegui.__version__)"  # 应该 >= 3.16

# 3. 测试无头启动
cd D:/Projects/Cercus
python test_server.py  # 应该输出 [OK] /monitor page rendered successfully

# 4. 实际启动（图形桌面环境）
python main.py
```

## 日志收集

如果遇到问题，收集日志：

```bash
cd D:/Projects/Cercus
python main.py > startup.log 2>&1
```

然后查看 `startup.log` 文件内容。
