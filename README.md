# MailVerifyPro (DomainValidator)

![Version](https://img.shields.io/badge/version-1.0.0-blue.svg)
![Python](https://img.shields.io/badge/python-3.9%2B-blue.svg)
![FastAPI](https://img.shields.io/badge/FastAPI-0.111.0-009688.svg?logo=fastapi)
![PostgreSQL](https://img.shields.io/badge/PostgreSQL-16-336791.svg?logo=postgresql)

Enterprise-grade, high-performance web application for bulk email validation. MailVerifyPro processing engine efficiently validates thousands of emails through a multi-tiered pipeline minimizing API costs and maximizing accuracy.

---

## 📑 Table of Contents
- [Overview](#-overview)
- [Key Features](#-key-features)
- [Architecture & Processing Pipeline](#-architecture--processing-pipeline)
- [Technology Stack](#-technology-stack)
- [Prerequisites](#-prerequisites)
- [Installation & Deployment](#-installation--deployment)
  - [Docker (Recommended)](#docker-recommended)
  - [Local Development](#local-development)
- [Environment Variables](#-environment-variables)
- [Usage Guide](#-usage-guide)
- [License](#-license)

---

## 🌟 Overview
MailVerifyPro handles massive lists of email addresses (CSV, XLS, XLSX) and filters out invalid, catch-all, and non-existent emails before you use them for outreach campaigns. By leveraging local heuristics, DNS pre-checks, and the powerful [NeverBounce](https://neverbounce.com/) API, it significantly reduces bounce rates.

## 🚀 Key Features
- **Bulk Upload Support**: Process batches of up to 20,000+ emails easily.
- **Cost Saving Engine**: Multi-tiered validation filtering prevents paying for obvious invalid emails.
- **Enterprise SSO Integration**: Includes Microsoft Authentication support via MSAL.
- **Real-time Progress Tracking**: Live UI updates indicating exact background processing status.
- **Detailed Analytics**: Validation breakdowns (Valid, Invalid, Catch-all, Domain Mismatch).
- **Automated Deduplication**: Automatically blocks the upload of identically named files to prevent redundant billing.
- **Excel Write-back**: Automatically appends results into new columns in your original file.

---

## ⚙️ Architecture & Processing Pipeline

MailVerifyPro employs a highly optimized, non-blocking asynchronous pipeline executing validation in the background.

```mermaid
graph TD
    %% Styling
    classDef ui fill:#f8fafc,stroke:#cbd5e1,stroke-width:2px,color:#0f172a
    classDef api fill:#f0fdf4,stroke:#86efac,stroke-width:2px,color:#166534
    classDef db fill:#eff6ff,stroke:#93c5fd,stroke-width:2px,color:#1e40af
    classDef worker fill:#fdf4ff,stroke:#f0abfc,stroke-width:2px,color:#86198f
    classDef external fill:#fff7ed,stroke:#fdba74,stroke-width:2px,color:#9a3412

    %% Components
    UI[Frontend UI (Jinja2 / Vanilla JS)]:::ui
    Router[FastAPI Upload Router]:::api
    Postgres[(PostgreSQL Vector DB)]:::db
    Worker[[Background Validation Worker]]:::worker
    NeverBounce((NeverBounce API)):::external
    ExcelWriter[Excel Write-back Service]:::worker

    %% Flow
    UI -->|Uploads CSV / Excel| Router
    Router -->|Checks for Duplicate Names| Postgres
    Router -->|Saves Uploaded File Data| Postgres
    Router -->|Triggers Background Task| Worker

    subgraph "Validation Pipeline (Per Record)"
        Worker -->|Step 1: Domain Match| DM{Domain Matches Target?}
        DM -->|Mismatch / Missing| Log1[Log: Domain Mismatch]
        DM -->|Match| PreCheck{Step 2: Syntax / DNS Pre-check}
        PreCheck -->|Invalid Format| Log2[Log: Invalid]
        PreCheck -->|Valid| Queue(Queue for Batching)
    end

    Queue -->|Step 3: Bulk Verification| NeverBounce
    NeverBounce -->|Returns Valid / Invalid / Catch-all| Log3[Log: API Result]

    Log1 -.->|Stores Logs in chunks| Postgres
    Log2 -.->|Stores Logs in chunks| Postgres
    Log3 -.->|Stores Logs in chunks| Postgres

    Log1 -.->|Writes result| ExcelWriter
    Log2 -.->|Writes result| ExcelWriter
    Log3 -.->|Writes result| ExcelWriter

    ExcelWriter -->|Generates Result File| UI
```

**The 3-Step Validation Pipeline:**
1. **Domain Matching (Local, Zero-cost):** Checks if the email domain matches the target prospect company website domain. Discards explicit mismatches immediately.
2. **Syntax Pre-check (Local, Zero-cost):** Checks regex patterns to ensure valid RFC-compliant formatting.
3. **NeverBounce Verification (API):** Only syntactically correct and domain-matched emails are forwarded to NeverBounce for deep SMTP handshake checks.

---

## 🛠 Technology Stack

**Backend System**
- **Framework**: [FastAPI](https://fastapi.tiangolo.com/) (High performance, async native)
- **Database**: PostgreSQL 16 (via pgvector Docker Image)
- **ORM**: SQLAlchemy 2.0
- **Data Serialization**: Pydantic V2
- **File Processing**: OpenPyXL

**Frontend UI**
- **Templates**: Jinja2
- **Styling**: Tailwind CSS / Vanilla CSS (Modern Glassmorphism UI)
- **State Management**: Vanilla JavaScript (Fetch API)

**Integrations**
- **Validation**: NeverBounce Python SDK
- **Identity**: Microsoft Authentication Library (MSAL)

---

## 📋 Prerequisites
Before you begin, ensure you have the following installed:
- [Docker](https://docs.docker.com/get-docker/) and [Docker Compose](https://docs.docker.com/compose/install/) (For containerized deployment)
- Python 3.9+ (For local bare-metal deployment)
- A [NeverBounce API Key](https://neverbounce.com/developer/api)
- Microsoft Azure AD App Credentials (For SSO)

---

## 💻 Installation & Deployment

### Docker (Recommended)
Deploying via Docker simplifies environment setup and spins up the PostgreSQL database automatically.

1. **Clone the repository:**
   ```bash
   git clone <repository_url>
   cd DomainValidator
   ```

2. **Configure Environment:**
   Create a `.env` file in the root directory (see [Environment Variables](#-environment-variables)).

3. **Build and Start Services:**
   ```bash
   docker-compose up -d --build
   ```

4. **Access the application:**
   Navigate to `http://localhost:8000` via your web browser.

### Local Development
1. **Set up a virtual environment:**
   ```bash
   python -m venv venv
   source venv/bin/activate  # On Windows: venv\Scripts\activate
   ```

2. **Install dependencies:**
   ```bash
   pip install -r requirements.txt
   ```

3. **Set up Local PostgreSQL:**
   Ensure PostgreSQL is running locally and update your `DATABASE_URL` appropriately in `.env`.

4. **Launch the FastAPI Server:**
   ```bash
   uvicorn main:app --host 0.0.0.0 --port 8000 --reload
   ```

---

## 🔑 Environment Variables
Your `.env` file must contain the following configurations:

```env
# Database Configuration
DATABASE_URL=postgresql://postgres:Raki@9515@localhost:5432/domain_validatorv2

# JWT Authentication
SECRET_KEY=your_secure_random_secret_key
ALGORITHM=HS256
ACCESS_TOKEN_EXPIRE_MINUTES=1440

# NeverBounce Configuration
NEVERBOUNCE_API_KEY=your_neverbounce_private_api_key

# Microsoft SSO (Optional/If enabled)
MS_CLIENT_ID=your_azure_client_id
MS_CLIENT_SECRET=your_azure_client_secret
MS_TENANT_ID=your_azure_tenant_id
```

---

## 📖 Usage Guide
1. **Login:** Access the portal via standard credentials or Microsoft SSO.
2. **Upload a List:** Navigate to the "Lists" tab and upload a formatted `.csv`, `.xls`, or `.xlsx`.
3. **Wait for Processing:** The UI will poll the server and present a real-time progress bar. Large files process asynchronously in chunks to prevent memory overload.
4. **Review Analytics:** Once complete, review the exact breakdown of "Valid", "Catch-all", "Unknown", etc.
5. **Download Results:** Your original file is modified with new appended columns containing the exact validation results.

---

## 🛡️ License
Proprietary Intellectual Property. All rights reserved. 
Unauthorized copying of this file, via any medium, is strictly prohibited.
