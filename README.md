<a id="readme-top"></a>

<!-- PROJECT LOGO -->
<br />
<div align="center">
  <h3 align="center">Voice Fleet Assistant</h3>

  <p align="center">
    A voice assistant for truck drivers to report maintenance issues, get safety guidance, and notify dispatch.
  </p>
</div>


<!-- ABOUT THE PROJECT -->
## About The Project

Voice Fleet Assistant is a browser-based voice assistant that lets truck drivers report maintenance issues, receive safety guidance, and notify dispatch. The driver speaks, the system reasons over the transcript using a Groq LLM, returns a short voice-safe response, speaks it aloud via ElevenLabs, and logs the issue for dispatch and maintenance.

If Groq is unavailable, the system automatically falls back to local rule-based safety logic so drivers are never left without a response.



### Built With

* [![Python][Python.org]][Python-url]
* [![FastAPI][FastAPI.tiangolo.com]][FastAPI-url]
* [![Groq][Groq.com]][Groq-url]
* [ElevenLabs](https://elevenlabs.io)




<!-- GETTING STARTED -->
## Getting Started

### Prerequisites

* Python 3.9 or later
* A [Groq API key](https://console.groq.com)
* An [ElevenLabs API key](https://elevenlabs.io)

### Installation

1. Clone the repo
   ```sh
   git clone https://github.com/sanskritim05/voice-fleet-assistant.git
   cd voice-fleet-assistant
   ```
2. Create and activate a virtual environment
   ```sh
   python -m venv venv
   source venv/bin/activate
   ```
3. Install dependencies
   ```sh
   pip install -r requirements.txt
   ```
4. Configure environment variables
   ```sh
   cp .env.example .env
   ```
   Add your API keys to `.env`:
   ```env
   ELEVENLABS_API_KEY=your_elevenlabs_api_key
   GROQ_API_KEY=your_groq_api_key
   ```
   Optional:
   ```env
   ELEVENLABS_VOICE_ID=your_voice_id
   GROQ_MODEL=llama-3.1-8b-instant
   ```
5. Start the server
   ```sh
   uvicorn app.main:app --reload
   ```
6. Open in your browser
   ```text
   http://127.0.0.1:8000
   ```


<!-- USAGE -->
## Usage

Open the web interface and speak directly into your browser. The assistant will transcribe your voice, reason over the input, respond aloud, and log the issue automatically.



<!-- HOW IT WORKS -->
## How It Works

| Step | Description |
|------|-------------|
| **Listen** | Browser captures voice input and sends the transcript to the FastAPI backend |
| **Reason** | Groq LLM classifies the incident by category, severity, and recommended action using a constrained output schema |
| **Respond** | A short, voice-safe response is generated and spoken back to the driver via ElevenLabs |
| **Log** | The incident is written to a JSON log for dispatch and maintenance review |
| **Fallback** | If Groq is unavailable, local rule-based safety logic handles the response automatically |

> Output is constrained to a conservative decision set, the system flags and routes; it does not make autonomous safety calls.




<!-- DEMO PHRASES -->
## Demo Phrases

Try saying any of the following:

* "My brakes are making a grinding noise."
* "My tire pressure light just came on."
* "The engine temperature is rising."
* "I need to tell dispatch I am delayed."
* "Can I keep driving if my check engine light is on?"


<!-- LICENSE -->
## License

Distributed under the MIT License. See `LICENSE.txt` for more information.


<!-- MARKDOWN LINKS & IMAGES -->
[contributors-shield]: https://img.shields.io/github/contributors/sanskritim05/voice-fleet-assistant.svg?style=for-the-badge
[contributors-url]: https://github.com/sanskritim05/voice-fleet-assistant/graphs/contributors
[forks-shield]: https://img.shields.io/github/forks/sanskritim05/voice-fleet-assistant.svg?style=for-the-badge
[forks-url]: https://github.com/sanskritim05/voice-fleet-assistant/network/members
[stars-shield]: https://img.shields.io/github/stars/sanskritim05/voice-fleet-assistant.svg?style=for-the-badge
[stars-url]: https://github.com/sanskritim05/voice-fleet-assistant/stargazers
[issues-shield]: https://img.shields.io/github/issues/sanskritim05/voice-fleet-assistant.svg?style=for-the-badge
[issues-url]: https://github.com/sanskritim05/voice-fleet-assistant/issues
[license-shield]: https://img.shields.io/github/license/sanskritim05/voice-fleet-assistant.svg?style=for-the-badge
[license-url]: https://github.com/sanskritim05/voice-fleet-assistant/blob/master/LICENSE.txt
[linkedin-shield]: https://img.shields.io/badge/-LinkedIn-black.svg?style=for-the-badge&logo=linkedin&colorB=555
[linkedin-url]: https://linkedin.com/in/sanskriti-m-937650330
[product-screenshot]: images/screenshot.png
[Python.org]: https://img.shields.io/badge/Python-3776AB?style=for-the-badge&logo=python&logoColor=white
[Python-url]: https://python.org
[FastAPI.tiangolo.com]: https://img.shields.io/badge/FastAPI-009688?style=for-the-badge&logo=fastapi&logoColor=white
[FastAPI-url]: https://fastapi.tiangolo.com
[Groq.com]: https://img.shields.io/badge/Groq-F55036?style=for-the-badge&logoColor=white
[Groq-url]: https://groq.com