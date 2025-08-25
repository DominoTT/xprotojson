# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

A Feishu (Lark) Sheets integration toolkit that provides data APIs, intelligent caching, and structured data transformation:

- **FastAPI Application** (`app/`): Web API service with health checks, data endpoints, and sync functionality
- **Core Library** (`python/`): Minimal FeishuClient for authentication and Sheets operations  
- **JSON Schema Services** (`python/json_schema/`): Generate JSON schemas from sheet headers and convert sheet data to structured objects
- **Data Services** (`app/services/`): Sheet synchronization, indexing, caching, and data transformation

## Development Setup

### Environment Setup

Set up Python virtual environment and install dependencies:

```bash
python -m venv .venv && source .venv/bin/activate
pip install -r app/requirements.txt
```

### Feishu Credentials Configuration

Configure Feishu API credentials (choose one method):

1. Environment variables:
```bash
export FEISHU_APP_ID="your_app_id"
export FEISHU_APP_SECRET="your_app_secret"
```

2. Config file: Edit `python/configs/xpj.feishu.yaml`:
```yaml
auth:
  app_id: "your_app_id"  
  app_secret: "your_app_secret"
```

### Running the Application

Start the FastAPI server:
```bash
uvicorn app.main:app --reload
```

Access health check: http://127.0.0.1:8000/api/v1/health

## Running Tests

Use pytest for testing:
```bash
# Run all tests
pytest

# Run specific test file
pytest tests/clients/test_feishu_client.py

# Run tests with verbose output
pytest -v

# Run the comprehensive integration test suite
python python/test/test.py
```

## Core Architecture

### Dual Structure Design
The project maintains two parallel structures:
- `app/`: FastAPI web service layer with dependency injection and data APIs
- `python/`: Core library that can be used standalone

### Key Components

**FeishuClient** (`python/core/feishu_client.py`): 
- Minimal Feishu API client using lark-oapi SDK
- Handles authentication via environment variables or config file
- Supports Sheets v3 (list sheets) and v2 (read values) APIs
- Drive v1 API for file listing

**FeishuSchemaService** (`python/json_schema/feishu_service.py`):
- Generates JSON Schema from spreadsheet headers
- Converts sheet data to structured objects
- Supports workbook-level schema aggregation
- Optional disk caching for schemas

**SheetSyncService** (`app/services/sheet_sync_service.py`):
- Synchronizes Feishu sheets to Redis with intelligent parsing
- Extracts table groups from sheet names (e.g., `Base(Group)`)
- Builds schemas from header rows and transforms data to structured JSON
- Maintains table metadata and source tracking

**IndexBuilder** (`app/services/index_builder.py`):
- Maintains ZSet indexes for table rows (`xpj:ids:{table}`)
- Supports grouped indexing by fields like Subtype
- Provides efficient ID-based queries with pagination
- Handles row updates with proper index maintenance

**FastAPI Dependency Injection** (`app/services/dependencies.py`):
- FeishuClient singleton managed via app.state
- Service layer with Redis, transformers, and sync services
- Global service instances with lazy initialization

### Data Flow
1. FeishuClient authenticates and fetches sheet metadata/data
2. SheetSyncService parses headers to generate schemas
3. Raw sheet data transformed to structured objects with ID keys
4. IndexBuilder maintains sorted indexes for efficient queries
5. Data cached in Redis with schema metadata
6. FastAPI endpoints provide sync and query functionality

## API Endpoints

### Data Sync
- `POST /api/v1/data/sheets/{sheet_token}/sync` - Sync specific sheet to Redis
- `POST /api/v1/data/folders/{folder_token}/sync` - Sync all sheets in folder
- `POST /api/v1/data/folders/sync` - Sync default folder sheets

### Data Query
- `GET /api/v1/data/by-id?id={id}` - Query single data by ID from cfgid key
- `GET /api/v1/data/by-ids?ids={id1,id2,id3}` - Batch query multiple data by IDs
- `GET /api/v1/data/by-table?table={table}&offset={offset}&limit={limit}` - Query all data in table with pagination

### Health and Status  
- `GET /api/v1/health` - Service health check
- `GET /` - Basic root endpoint

## Important File Paths

When making changes, be aware of these key locations:
- `app/main.py:19` - FeishuClient initialization in startup event
- `app/services/dependencies.py` - Service dependency injection with global instances
- `app/services/sheet_sync_service.py` - Core sync logic and schema building
- `app/services/index_builder.py` - Redis ZSet index maintenance
- `app/api/v1/endpoints/data.py` - Data API endpoints
- `app/services/cache/redis_service.py` - Redis client wrapper
- `python/core/feishu_client.py:29` - Credential loading logic

## Path Configuration

When using the library standalone, ensure the project root is in PYTHONPATH:
```bash
export PYTHONPATH=$PWD:$PYTHONPATH
```

## Error Handling Patterns

The codebase uses specific error handling patterns:
- RuntimeError for API failures with detailed logging
- HTTPException for FastAPI endpoint errors
- Graceful fallbacks for missing dependencies (Redis, cache)
- Invalid ID handling in IndexBuilder (logs warnings and continues)
- Comprehensive logging via Python logging module with service-specific loggers