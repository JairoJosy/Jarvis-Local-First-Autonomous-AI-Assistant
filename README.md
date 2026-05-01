# 🚀 Jarvis — Local-First Autonomous AI Assistant

<img width="1536" height="1024" alt="image" src="https://github.com/user-attachments/assets/83937205-368b-4735-9eae-e31b0de496e0" />


> **An AI system that doesn’t just respond — it plans, acts, and remembers.**

---

## 🧠 What is Jarvis?

Jarvis is a **local-first autonomous AI assistant backend** designed to go beyond chat.

It combines:
- 🧩 LLM-based planning  
- 🛠️ Tool execution  
- 🧠 Persistent memory  
- 🔐 Safe, controlled actions  

Unlike traditional AI tools, Jarvis can **break down tasks, execute them step-by-step, and retain context across sessions.**

---

## ⚡ Real Execution (Visual Demo)

Instead of static examples, Jarvis demonstrates:

- ✅ Tool execution in real environments  
- ✅ Memory persistence across sessions  
- ✅ Multi-step reasoning and task completion  

> See the visual breakdown above 👆

---

## 🏗️ Architecture Overview

Jarvis follows a **controlled agent pipeline**:

User → Planner (LLM) → Authority Layer → Tool Executor → Memory → Response

- **Planner** → Breaks down tasks  
- **Authority Layer** → Validates safety  
- **Tool Executor** → Executes real actions  
- **Memory System** → Stores and retrieves context  

---

<img width="1536" height="1024" alt="image" src="https://github.com/user-attachments/assets/f02ab769-d31e-49af-a65c-3eeed356ec8d" />

---

## 🧩 Core Capabilities

### 🧠 Persistent Memory
- SQLite-based structured memory  
- Vector search (FAISS / fallback)  
- Cross-session recall  

### 🛠️ Tool Execution
- System tools (open apps, shell commands)  
- Schema-validated inputs  
- Controlled execution with approval  

### 🔄 Autonomous Planning
- Task decomposition  
- Multi-step execution  
- Structured reasoning pipeline  

### 🔐 Safety & Control
- Authority validation layer  
- Tiered tool permissions  
- Human-in-the-loop approvals  

### ⚡ Hybrid Model Support
- Local models (Ollama / llama.cpp)  
- Cloud models (Groq / OpenRouter)  
- Intelligent routing  

### 📊 Observability
- Full audit logs  
- Timeline tracking  
- Transparent execution flow  

---

## 🧪 Tech Stack

- **Backend:** FastAPI  
- **Language:** Python 3.11+  
- **Memory:** SQLite + FAISS / NumPy  
- **LLMs:** Groq + Ollama  
- **Validation:** Pydantic  

Optional:
- Voice → Vosk / Whisper  
- Media → FFmpeg / Pillow  
- Web QA → Playwright / Lighthouse  

---

<img width="1536" height="1024" alt="image" src="https://github.com/user-attachments/assets/9d6f6bcb-18a6-4c36-98d6-2379e5640e5c" />

---
## ⚙️ Getting Started

### 1. Clone the repository
```bash
git clone https://github.com/your-username/jarvis.git
cd jarvis
```

### 2. Install dependencies
```bash
pip install -r requirements.txt
```

### 3. Run the server
```bash
uvicorn server:app --reload
```

### 4. Open UI
http://localhost:8000/ui

---

## 📁 Project Structure

jarvis/
 ├── app/
 ├── memory/
 ├── tools/
 ├── orchestrator/
 ├── v2/
 ├── assets/
 └── docs/

---

## 🚧 Current Status

- ✅ Planning & execution pipeline  
- ✅ Persistent memory system  
- ✅ Tool execution with safety  
- ✅ Task workflows  
- ⚠️ UI and integrations evolving  

---

## 🌍 Vision

Jarvis is built toward a future where AI systems:

- Don’t just answer → **they take action**  
- Don’t forget → **they build context over time**  
- Don’t act blindly → **they operate safely**  

---

## ⭐ Why this project matters

Most AI tools today are **stateless and reactive**.

Jarvis is different:

> 👉 It is designed to **plan, execute, and remember in real-world environments.**

---

## 📬 Contact

**Jairo Josy**  
AI • Robotics • Systems Builder  
🔗 LinkedIn:
https://www.linkedin.com/in/jairo-josy
