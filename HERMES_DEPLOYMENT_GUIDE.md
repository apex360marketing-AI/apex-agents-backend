# APEX Agents Backend — Hermes Deployment Guide

## Quick Deploy to Railway (5 minutes)

### Prerequisites
- Railway account + API token
- This repo cloned locally

### Option 1: Using GitHub Actions (Automated)
1. Add `RAILWAY_TOKEN` secret to GitHub repo
2. Push to main branch
3. GitHub Actions auto-deploys to Railway
4. Done ✅

### Option 2: Manual Railway Deploy
```bash
# Install Railway CLI
npm install -g @railway/cli

# Authenticate
railway login

# Deploy
cd apex-agents-backend
railway up --service apex-agents-backend
```

### What Gets Deployed
- FastAPI server with 23 REST endpoints
- Real-time lead scoring engine
- Trial account management system
- API key rotation system
- Email & Slack integration support

### Environment
- Python 3.11
- uvicorn (ASGI server)
- Dependencies in requirements.txt

### Start Command
```
uvicorn confidence_api:app --host 0.0.0.0 --port $PORT
```

### Expected Output After Deploy
```
INFO:     Application startup complete
Uvicorn running on http://0.0.0.0:8000
```

### Test Deployment
```bash
# Get your Railway URL and run:
curl https://your-railway-url.railway.app/health
# Should return: {"status": "healthy"}
```

## Files Included
- `confidence_api.py` - Main API server
- `signup_system.py` - Trial account management
- `confidence_engine.py` - Scoring logic
- `vertical_models.py` - Vertical-specific models
- `requirements.txt` - Python dependencies
- `Procfile` - Procfile for deployments
- `Dockerfile` - Docker containerization
- `railway.json` - Railway config

## Success Criteria
- ✅ Backend deployed to Railway
- ✅ GET /health returns 200
- ✅ POST /api/auth/signup accepts requests
- ✅ No errors in Railway logs

---

**Questions?** Check the main README.md or contact the team.
