# ZealFlow

Reference-driven AI batch image generation for Zeal's creative workflow.

## Core workflow
1. Upload Front reference, Back reference, or both.
2. Import up to 99 raw images directly and/or from a ZIP.
3. Choose Default, Custom, or Skip custom prompt mode.
4. Choose Auto/reference aspect ratio or manual ratio, quality, and preservation.
5. Generate, preview Before/After, retry failures, download single files or the full ZIP.
6. Re-open previous local batches from History.

## macOS
```bash
bash SETUP_PROJECT.sh
# Add OPENAI_API_KEY to .env
bash START_PROJECT.sh
```

## Windows
Run `SETUP_PROJECT_WINDOWS.bat`, add `OPENAI_API_KEY` to `.env`, then run `START_PROJECT_WINDOWS.bat`.

Frontend: http://127.0.0.1:5173
Backend: http://127.0.0.1:8000

## Environment
See `.env.example`. Keep `.env` private and never commit it.


## ZealFlow V5 Ready changes
- Clean workspace: no bundled test jobs/images.
- OpenAI API key is entered from Sidebar > API Key and saved in browser localStorage. `.env` key is only an optional fallback.
- Firebase Admin Storage support is included. When Firebase env values are configured, references, inputs, generated outputs and the final ZIP are mirrored to Cloud Storage under `zealflow/jobs/<job_id>/...`.

### Firebase Storage setup
1. In Firebase Console, enable Storage for your project.
2. Project Settings > Service Accounts > Firebase Admin SDK > Generate new private key. Keep that JSON outside this project and never commit it.
3. Put these values in `.env`:
```env
FIREBASE_STORAGE_BUCKET=your-project-id.firebasestorage.app
GOOGLE_APPLICATION_CREDENTIALS=/absolute/path/to/firebase-service-account.json
FIREBASE_STORAGE_PREFIX=zealflow
```
4. Run the setup script again (or `pip install -r requirements.txt`) so `firebase-admin` is installed.
5. Restart ZealFlow. `GET /api/health` will show `firebase_storage: true` when configured.

### OpenAI API key
Open ZealFlow > API Key > paste your key > Save API Key. The browser sends it only when starting/retrying generation. It is not saved into job history or source files.
