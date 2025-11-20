# SSO Backend Docker Image

This directory contains a Dockerized SSO Backend service for Azure AD authentication.

## 📋 Prerequisites

- Docker installed on your system
- Azure AD app registration with:
  - Client ID
  - Client Secret
  - Tenant ID
  - Redirect URI configured

## 🚀 Quick Start

### 1. Configure Environment Variables

Copy the example environment file and fill in your Azure AD credentials:

```bash
cp .env.example .env
```

Edit `.env` and set your values:
```env
TENANT_ID=your-tenant-id
CLIENT_ID=your-client-id
CLIENT_SECRET=your-client-secret
REDIRECT_URI=http://localhost:5500/mcp_sso_test.html
```

### 2. Build the Docker Image

```bash
docker build -t sso-backend:latest .
```

### 3. Run with Docker

```bash
docker run -d \
  --name sso_backend \
  -p 8000:8000 \
  --env-file .env \
  sso-backend:latest
```

### 4. Run with Docker Compose (Recommended)

```bash
# Start the service
docker-compose up -d

# View logs
docker-compose logs -f

# Stop the service
docker-compose down
```

## 🔧 Available Commands

### Docker Commands

```bash
# Build image
docker build -t sso-backend:latest .

# Run container
docker run -d --name sso_backend -p 8000:8000 --env-file .env sso-backend:latest

# View logs
docker logs -f sso_backend

# Stop container
docker stop sso_backend

# Remove container
docker rm sso_backend

# Access container shell
docker exec -it sso_backend /bin/bash
```

### Docker Compose Commands

```bash
# Start services in detached mode
docker-compose up -d

# Start and rebuild
docker-compose up -d --build

# View logs
docker-compose logs -f

# Stop services
docker-compose down

# Stop and remove volumes
docker-compose down -v

# Restart service
docker-compose restart
```

## 🧪 Testing

### Health Check

```bash
curl http://localhost:8000/health
```

Expected response:
```json
{"status":"ok"}
```

### Test Authentication Flow

1. Ensure the backend is running
2. Open your HTML frontend
3. Click "Start SSO"
4. Sign in with Microsoft
5. Check user info

## 📊 Endpoints

- `GET /health` - Health check endpoint
- `GET /auth/login` - Initiate SSO login
- `GET /auth/callback` - OAuth2 callback handler
- `GET /auth/me` - Get authenticated user info
- `POST /auth/logout` - Logout user

## 🔐 Environment Variables

| Variable | Required | Default | Description |
|----------|----------|---------|-------------|
| `TENANT_ID` | ✅ Yes | - | Azure AD Tenant ID |
| `CLIENT_ID` | ✅ Yes | - | Azure AD Application (client) ID |
| `CLIENT_SECRET` | ✅ Yes | - | Azure AD Client Secret |
| `REDIRECT_URI` | ✅ Yes | - | OAuth2 redirect URI |
| `COOKIE_SECRET` | No | `changeme` | Session cookie encryption key |
| `COOKIE_NAME` | No | `sso_session` | Session cookie name |
| `AUTH_BASE_URL` | No | `http://localhost:8000` | Backend base URL |
| `CORS_ALLOWED_ORIGINS` | No | `*` | CORS allowed origins |
| `LOG_LEVEL` | No | `info` | Logging level |
| `DISABLE_SSL_VERIFY` | No | `False` | Disable SSL verification |

## 🐳 Docker Image Details

- **Base Image**: `python:3.11-slim`
- **Exposed Port**: `8000`
- **Health Check**: Enabled (checks `/health` every 30s)
- **Restart Policy**: `unless-stopped`

## 📝 Notes

- For production use, set `secure=True` for cookies and enable SSL
- Use proper session storage (Redis, database) instead of in-memory
- Enable JWT signature verification in production
- Restrict CORS origins to specific domains
- Use secrets management for sensitive credentials

## 🛠️ Troubleshooting

### Container won't start

```bash
# Check logs
docker logs sso_backend

# Check if port 8000 is already in use
netstat -ano | findstr :8000  # Windows
lsof -i :8000  # Linux/Mac
```

### Environment variables not loaded

Ensure your `.env` file exists and contains all required variables.

```bash
# Verify environment variables in container
docker exec sso_backend env | grep TENANT_ID
```

### Health check fails

```bash
# Test health endpoint manually
docker exec sso_backend curl http://localhost:8000/health
```

## 📦 Production Deployment

For production deployment:

1. Use a proper secrets manager (Azure Key Vault, AWS Secrets Manager)
2. Enable HTTPS/TLS
3. Use production-grade WSGI server settings
4. Implement proper logging and monitoring
5. Set up container orchestration (Kubernetes, ECS)
6. Configure proper network policies
7. Enable security scanning

## 📄 License

[Your License Here]
