# 边境日志

文字优先的勇士放置游戏原型。游戏规则、时间推进和离线结算位于 `src/game-engine`，UI 和浏览器存档与其解耦。装备耐久每场战斗下降，耐久归零后保留破损保护属性但仍可继续战斗。

## 本地运行

```powershell
npm install
npm run dev
```

## 验证

```powershell
npm run typecheck
npm run test
npm run build
npm run test:e2e
```

当前 Node 环境建议使用 Node 20 或更高版本。浏览器存档保存在 `localStorage`，可从游戏内导出或导入 JSON。

> 当前执行环境的 npm registry 代理（`127.0.0.1:7897`）无法连接，因此本次无法完成依赖安装、类型检查、测试和生产构建。源码与测试已写入，网络恢复后执行上面的验证命令即可。
