# 参与共创

欢迎提交缺陷、功能建议和非商业用途的改进。本项目为**非商业源码公开**项目，不是允许商业使用的 OSI 开源项目。

1. 先搜索 Issues，较大改动先开 Issue 讨论需求与兼容性。
2. Fork 本仓库，新建功能分支，以小范围 Pull Request 提交。
3. 保持现有目录索引和原文件安全，不引入自动删除原素材、覆盖同名还原或云端上传行为。
4. 不提交个人素材、NAS 地址、标签数据库、缓存、账号凭据或他人未授权的字体/图标。
5. 新依赖需说明许可证；不要引入与非商业分发方案不兼容的组件。
6. 提交你有权授权的原创或兼容许可内容；贡献按仓库 LICENSE 许可，不要求转让版权。

## 验证

```sh
python3 -m venv .venv
# 激活虚拟环境后：
python -m pip install -r requirements.txt
python -m unittest discover -s tests -p 'test_*.py'
npm install
npm test
```

源码运行需要可用 FFmpeg。发行构建使用 `packaging/prepare_ffmpeg.py` 编译的 LGPL-only 独立程序；开发环境可使用自己安装的 FFmpeg。请不要将外部组件误标成本项目的非商用许可证。

Python 使用 Black，前端使用 Prettier。请在 PR 中说明具体触发场景、修改后的行为、验证结果及受影响平台。Windows 或真实 NAS 未测试时请明确标注。
