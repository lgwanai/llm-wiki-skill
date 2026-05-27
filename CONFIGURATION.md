# LLM Wiki v2 配置指南

本文档详细说明 LLM Wiki v2 的配置选项和使用方法。

---

## 快速开始

```bash
# 1. 创建配置文件
wiki config --init

# 2. 编辑配置文件，设置 API key
vim wiki_config.yaml

# 3. 初始化 Wiki
wiki init

# 4. 开始使用
wiki compile source.md
wiki query "What is X?"
```

---

## 配置文件位置

配置文件按以下优先级查找：

1. **环境变量**: `LLM_WIKI_CONFIG` 指定的路径
2. **当前目录**: `./wiki_config.yaml`
3. **父目录**: 向上递归查找
4. **用户目录**: `~/.config/llm-wiki/wiki_config.yaml`

推荐将配置文件放在项目根目录或用户配置目录。

---

## Wiki 目录配置

### wiki_dir

指定 Wiki 数据存储根目录，编译后的页面存放在此。

```yaml
wiki_dir: .wiki          # 相对路径（推荐）
wiki_dir: ~/.wiki        # 用户主目录
wiki_dir: /data/wiki     # 绝对路径
```

也可以通过环境变量覆盖：

```bash
export LLM_WIKI_DIR=/path/to/wiki
```

---

## LLM 模型配置

LLM Wiki 支持三种模型调用模式：

### 1. DeepSeek API（默认）

```yaml
llm:
  provider: deepseek
  api_key: "sk-xxx"                    # 必填
  base_url: "https://api.deepseek.com"
  model: "deepseek-v4-flash"           # 或 deepseek-chat
  temperature: 0.3
  max_tokens: 32000
```

### 2. OpenAI API

```yaml
llm:
  provider: openai
  api_key: "sk-xxx"
  base_url: "https://api.openai.com"
  model: "gpt-4o"                      # 或 gpt-4o-mini
  temperature: 0.3
  max_tokens: 32000
```

### 3. Ollama 本地模型

```yaml
llm:
  provider: ollama

ollama:
  base_url: "http://localhost:11434"
  model: "llama3.2"                   # 或 qwen2.5, deepseek-r1:7b
  temperature: 0.3
  num_ctx: 32768                       # 上下文窗口大小
  embedding_model: "nomic-embed-text"  # 用于向量搜索
```

使用本地模型无需 API key，完全离线运行。

### 4. 自定义 API 端点

适用于自部署的 OpenAI 兼容服务：

```yaml
llm:
  provider: custom

custom:
  base_url: "http://your-server:8000"
  api_key: "your-custom-key"
  model: "your-model-name"
```

或直接指定完整 URL：

```yaml
custom:
  api_url: "http://your-server:8000/v1/chat/completions"
  api_key: "your-custom-key"
  model: "your-model-name"
```

---

## 环境变量

所有配置都支持环境变量替换：

```yaml
llm:
  api_key: ${DEEPSEEK_API_KEY}    # 从环境变量读取
  base_url: ${API_BASE_URL}
```

敏感信息推荐使用环境变量：

```bash
# ~/.bashrc 或 ~/.zshrc
export DEEPSEEK_API_KEY="sk-xxx"
export LLM_WIKI_DIR="$HOME/.wiki"
```

---

## 查询配置

```yaml
query:
  # 是否使用 LLM 合成答案
  # true: 调用 LLM 生成结构化答案（慢，2-3秒）
  # false: 仅返回搜索结果（快，0.5秒）
  llm_synthesis: true
  
  # 默认输出格式
  default_format: markdown    # markdown | table | timeline | slides | json
  
  # 搜索结果数量上限
  max_results: 5
```

---

## OCR 后端配置

LLM Wiki 支持三种 OCR 引擎：

### MinerU（推荐）

纯 CPU 运行，支持公式转 LaTeX、表格转 HTML：

```yaml
mineru:
  backend: pipeline
  lang: ch           # ch | en
  formula: true      # 识别公式
  table: true        # 识别表格
```

安装：
```bash
uv pip install -U "mineru[all]"
```

### PaddleOCR

支持 109 种语言，文档纠偏：

```yaml
paddleocr:
  lang: ch
  use_doc_orientation_classify: true
  use_doc_unwarping: true
```

安装：
```bash
pip install paddleocr paddlepaddle
```

### DeepSeek-OCR

需要 GPU 或 API：

```yaml
ocr:
  api_url: "http://127.0.0.1:12345/v1/chat/completions"
  api_key: "your-ocr-api-key"
  model: "DeepSeek-OCR-4bit"
```

---

## 知识保留配置

不同类型知识有不同的遗忘曲线：

```yaml
retention:
  architecture: {half_life_days: 180}    # 架构决策衰减慢
  project: {half_life_days: 130}
  pattern: {half_life_days: 87}
  bug: {half_life_days: 20}              # Bug 衰减快
  meeting: {half_life_days: 10}
  preference: {half_life_days: 527}       # 偏好长期有效
  
  stale_threshold: 0.5    # 低于此值标记为过期
  archive_threshold: 0.15 # 低于此值标记为归档
```

---

## 向量搜索配置

```yaml
embeddings:
  model: "sentence-transformers/all-MiniLM-L6-v2"
  dimension: 384
  backend: faiss          # faiss | qdrant
  cache_path: "graph/embeddings.json"
```

---

## CLI 使用

安装后直接使用 `wiki` 命令：

```bash
# 安装（开发模式）
pip install -e .

# 查看帮助
wiki --help

# 初始化
wiki init

# 配置管理
wiki config              # 显示当前配置
wiki config --init       # 创建配置文件

# 编译文档
wiki compile source.md
wiki compile paper.pdf --type article
wiki compile source.md --force

# 查询
wiki query "What is X?"
wiki query "compare models" --format table
wiki query "快速搜索" --no-synthesis

# 健康检查
wiki lint
wiki lint --auto-heal

# 批量操作
wiki bulk stats
wiki bulk clean --dry-run

# 状态
wiki status

# 向量嵌入
wiki embed
wiki embed --force
```

---

## 完整配置示例

```yaml
# Wiki 存储目录
wiki_dir: .wiki

# LLM 配置
llm:
  provider: deepseek
  api_key: ${DEEPSEEK_API_KEY}
  base_url: https://api.deepseek.com
  model: deepseek-v4-flash
  temperature: 0.3
  max_tokens: 32000

# 查询配置
query:
  llm_synthesis: true
  default_format: markdown
  max_results: 5

# OCR 配置
mineru:
  backend: pipeline
  lang: ch
  formula: true
  table: true

# 知识保留
retention:
  architecture: {half_life_days: 180}
  bug: {half_life_days: 20}

# 质量控制
quality:
  auto_heal: true
  min_score: 0.4

# 日志
logging:
  level: INFO
```

---

## 常见问题

### Q: 如何切换模型？

修改配置文件中的 `llm.provider` 和对应配置：

```yaml
# 切换到 Ollama 本地模型
llm:
  provider: ollama
ollama:
  model: llama3.2

# 切换到 OpenAI
llm:
  provider: openai
  api_key: ${OPENAI_API_KEY}
  model: gpt-4o
```

### Q: Wiki 目录可以放在哪？

任意位置，支持：
- 相对路径：`wiki_dir: .wiki`（相对于配置文件）
- 绝对路径：`wiki_dir: /data/wiki`
- 用户目录：`wiki_dir: ~/.wiki`
- 环境变量：`export LLM_WIKI_DIR=/path/to/wiki`

### Q: 如何调试配置问题？

```bash
# 查看当前配置
wiki config

# 直接运行配置模块
python -m scripts.config
```

### Q: 配置文件放哪最好？

推荐：
- 项目级：项目根目录的 `wiki_config.yaml`
- 用户级：`~/.config/llm-wiki/wiki_config.yaml`

环境变量 `LLM_WIKI_CONFIG` 可指定任意位置。

---

## 下一步

- 阅读 [README.md](../README.md) 了解完整功能
- 查看 [wiki_config.yaml.example](wiki_config.yaml.example) 配置模板
- 运行 `wiki --help` 查看所有命令
