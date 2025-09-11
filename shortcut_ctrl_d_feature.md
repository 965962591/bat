# Ctrl+D 快捷键功能

## 功能描述
为 rename.py 中的 FileOrganizer 类添加了 Ctrl+D 快捷键，用于快速清空右侧视图。

## 实现细节

### 1. 快捷键设置
在 `FileOrganizer` 类的 `initUI` 方法中添加了快捷键设置：

```python
# 添加Ctrl+D快捷键用于清空右侧视图
self.shortcut_remove_all = QShortcut(QKeySequence("Ctrl+D"), self)
self.shortcut_remove_all.activated.connect(self.remove_all_from_right)
```

### 2. 功能函数
调用现有的 `remove_all_from_right` 函数，该函数的功能包括：

- 清空右侧排除路径列表
- 重置代理模型的过滤器
- 清空包含路径列表
- 设置右侧视图为空目录
- 在状态栏显示操作反馈

### 3. 用户反馈
添加了状态栏消息提示，当用户按下 Ctrl+D 时会显示：
```
"已清空右侧视图 (Ctrl+D)"
```
消息会在 2 秒后自动消失。

## 使用方法
1. 在 FileOrganizer 窗口中按下 `Ctrl+D`
2. 右侧视图将被清空
3. 状态栏会显示确认消息

## 技术实现
- 使用 PyQt5 的 QShortcut 类创建快捷键
- 快捷键绑定到现有的 `remove_all_from_right` 方法
- 添加了用户友好的状态栏反馈
- 保持了原有功能的完整性

## 兼容性
- 与现有的 ESC 快捷键（退出）兼容
- 不影响其他快捷键功能
- 适用于 Windows 系统的 Ctrl+D 快捷键习惯

这个功能提供了快速清空右侧视图的便捷方式，提升了用户体验。