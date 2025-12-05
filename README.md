<h1 align="center">ADgent - Ad Generation Pipeline</h1>

<p align="center">
<img src="https://github.com/v-prgmr/aDgent/blob/main/frontend.png" alt="ADgent Frontend" width="730">
</p>

<p align="center"><b>AI-powered ad generation system that creates complete video ads with storyboards, scenes, and voiceovers.</b></p>

<p align="center">
<a href=""><img alt="Python Versions" src="https://img.shields.io/badge/python-3.9--3.15-dark_green"></a>
</p>

## Features

- 🎬 **Storyboard Generation**: Generate creative ad concepts using GPT-4
- 🎨 **Scene Image Generation**: Create visual scenes using Google Gemini
- 🎙️ **Voiceover Generation**: Professional text-to-speech using ElevenLabs
- 🖼️ **Character Assets**: Upload and manage character assets for consistent branding
- 🌐 **Web Scraping**: Analyze company websites for ad inspiration

## Setup

### 1. Create Virtual Environment (Recommended)

```bash
python3 -m venv venv
source venv/bin/activate  # On macOS/Linux
# or
venv\Scripts\activate  # On Windows
```

### 2. Install Dependencies

```bash
pip install -r requirements.txt
```

### 3. Configure Environment Variables

Create a `.env` file like `.env.example` in the project root:

```bash
# Google Generative AI
GOOGLE_API_KEY=your_google_api_key_here

# OpenAI
OPENAI_API_KEY=your_openai_api_key_here

# ElevenLabs TTS
ELEVENLABS_API_KEY=your_elevenlabs_api_key_here
```

### 4. Start the Server

From the repository root you can run the FastAPI app with Uvicorn:

```bash
uvicorn main:app --reload
```

If you are starting the server from another working directory, use the
convenience runner that sets the application directory for you:

```bash
python /path/to/ADgent/run_server.py --reload
```
TO spin the frontend up, you need to run the following from the `adgent-frontend` folder.

```bash
npm run build && npm run dev
```


The API will be available at `http://localhost:8000` in both cases.

## API Endpoints

### 1. Generate Ad Ideas

```bash
POST /generate-ad-ideas
Content-Type: application/json

{
  "company_url": "https://example.com",
  "product_description": "New eco-friendly water bottle"
}
```

### 2. Generate Storyboard

```bash
POST /generate-story-board?selected_idea=YOUR_STORY_IDEA
```

### 3. Upload Character Assets

```bash
POST /upload-char-asset
Content-Type: multipart/form-data

image: <file>
```

### 4. Generate Scene Images

```bash
POST /generate-scenes
```

### 5. Generate Voiceovers 

```bash
POST /generate-voiceovers

# Optional: specify custom voice
POST /generate-voiceovers?voice_id=YOUR_VOICE_ID
```

## Workflow

Complete ad generation workflow:

```bash
# 1. Generate storyboard
curl -X POST "http://localhost:8000/generate-story-board?selected_idea=Eco-friendly+coffee+shop+ad"

# 2. (Optional) Upload character assets
curl -X POST "http://localhost:8000/upload-char-asset" -F "image=@character.png"

# 3. Generate scene images
curl -X POST "http://localhost:8000/generate-scenes"

# 4. Generate voiceovers
curl -X POST "http://localhost:8000/generate-voiceovers"
```

## Output Structure

```
adgent/
├── images/
│   ├── generated_storyboard.json  # Storyboard data
│   ├── char_asset1.png            # Character assets
│   └── scene1.png                 # Scene references
├── generated_scenes/
│   └── website-slug
│       └── images/  
│           ├── scene1.png                 # Generated scenes
│           ├── scene2.png
│       └── audio/
│           ├── scene1_voiceover.mp3       # Voiceover audio files
│           └── scene2_voiceover.mp3
│       └── videos/
│           ├── scene1.mp4                 # Generate videos
│           └── scene2.mp4
│       └── final_video.mp4                # Generated final advertisement
```

## Tech Stack

- **FastAPI**: Web framework
- **Google Gemini 2.5**: Image generation
- **OpenAI GPT-4**: Storyboard generation
- **ElevenLabs**: Text-to-speech voiceovers
- **Pillow**: Image processing

## API Keys

- **Google Generative AI**: https://makersuite.google.com/app/apikey
- **OpenAI**: https://platform.openai.com/api-keys
- **ElevenLabs**: https://elevenlabs.io/app/settings

## Troubleshooting

### Virtual Environment Issues

If you get "externally-managed-environment" error:

```bash
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
```

### Missing API Keys

Ensure all required API keys are set in `.env` file and restart the server.

### Import Errors

Install dependencies in a virtual environment:

```bash
source venv/bin/activate
pip install -r requirements.txt
```
