> ## Documentation Index
> Fetch the complete documentation index at: https://www.bolna.ai/docs/llms.txt
> Use this file to discover all available pages before exploring further.

# Sarvam Transcriber (Speech to Text)

> Integrate Sarvam with your Bolna Voice AI agents for accurate Indian language transcription. Supports 11 Indian languages with Saarika and Saaras speech models.

## 1. What is Sarvam STT?

[Sarvam](https://sarvam.ai/) Speech-to-Text (STT) is an advanced automatic speech recognition (ASR) platform specifically designed for Indian languages. Sarvam specializes in understanding regional accents, code-mixed speech, and multilingual conversations common in the Indian subcontinent.

Sarvam's "Saarika" and "Saaras" models are built for real-time transcription with a focus on Indian language accuracy. Saarika provides transcription in the original language, while Saaras offers direct speech-to-English translation with automatic language detection, making them ideal solutions for voice-driven applications serving Indian markets.

## 2. Key Features of Sarvam STT

Sarvam offers specialized features for Indian language transcription:

* **Indian Language Expertise**: Deep neural networks specifically trained on diverse Indian language datasets, achieving high accuracy for regional accents and code-mixed speech patterns.

* **Real-Time Processing**: Designed for streaming transcription with low latency, enabling natural conversation flow in live applications.

* **Code-Mixed Speech Recognition**: Excels at understanding code-mixed languages, handling seamless switches between English and Indian languages within conversations.

* **Multilingual Support**: Supports 10 Indian languages including Hindi, Bengali, Tamil, Telugu, Gujarati, Kannada, Malayalam, Marathi, Punjabi, Odia, plus English (India).

* **Speaker Diarization**: Identifies and separates different speakers in audio streams for better conversation structure.

* **Voice Activity Detection**: Advanced VAD capabilities with configurable sensitivity levels for better speech boundary detection.

* **Automatic Language Detection**: Can automatically detect the spoken language when configured with "unknown" language code.

* **WebSocket Streaming**: Real-time streaming API for continuous speech recognition with immediate results and timestamp support.

## 3. How Bolna Uses Sarvam for STT

Bolna AI integrates Sarvam's STT technology to enable high-accuracy Indian language transcription for voice agents. Here's how Bolna leverages Sarvam:

* **Real-Time Indian Language Processing**:
  Bolna uses Sarvam's streaming STT API to convert Indian language speech into text in real time. This enables AI agents to understand and process user input in regional languages without delays.

* **Regional Language Voice Agent Support**:
  With Sarvam's specialized Indian language support, Bolna voice agents can handle conversations in Hindi, Bengali, Tamil, Telugu, and other regional languages with high accuracy.

* **Accent-Aware Transcription**:
  Bolna leverages Sarvam's training on diverse Indian accents and speaking patterns to ensure accurate transcription across different regions and demographics.

* **Voice Activity Detection for Better Accuracy**:
  Bolna uses Sarvam's VAD capabilities to detect speech boundaries accurately, improving conversation flow and reducing false transcriptions from background noise.

* **Indian Market Optimization**:
  Since Bolna serves businesses across India, Sarvam's focus on Indian languages and accents ensures better customer experience for regional market deployments.

* **Code-Switching Support**:
  Sarvam handles mixed language conversations common in India, where speakers switch between English and regional languages within the same conversation.

## 4. List of Sarvam models supported on Bolna AI

| Model        | Description                                                                                                          |
| ------------ | -------------------------------------------------------------------------------------------------------------------- |
| saarika:v2.5 | Speech-to-text transcription in original language                                                                    |
| saaras:v2.5  | Speech-to-English translation with automatic language detection                                                      |
| saaras:v3    | Speech-to-text transcription in original language (configured for STT transcription)                                 |
| saaras:v4    | Latest Saaras model for speech-to-text transcription in original language, with automatic language detection support |

## 5. Supported Languages

All Sarvam transcriber models support the following 11 languages:

* **English (India)** - en-IN
* **Hindi** - hi-IN
* **Bengali** - bn-IN
* **Tamil** - ta-IN
* **Telugu** - te-IN
* **Gujarati** - gu-IN
* **Kannada** - kn-IN
* **Malayalam** - ml-IN
* **Marathi** - mr-IN
* **Punjabi** - pa-IN
* **Odia** - od-IN

**Model Differences:**

* **Saarika v2.5**: Transcribes speech to text in the original spoken language
* **Saaras v2.5**: Translates speech directly to English text with automatic language detection
* **Saaras v3**: Configured for direct transcription in the original spoken language
* **Saaras v4**: Latest Saaras model, transcribes directly in the original spoken language and can auto-detect the spoken language

Note: All models excel at code-mixed speech where speakers seamlessly switch between English and any of the supported Indian languages within the same conversation.

## Conclusion

Sarvam's STT capabilities empower Bolna AI to deliver highly accurate, real-time speech-to-text transcription for Indian languages, making voice interactions seamless for regional markets. By integrating Sarvam's specialized ASR technology, Bolna enhances its ability to process diverse Indian accents, handle code-switching scenarios, and understand complex multilingual conversations, thereby improving the overall performance and reliability of its voice AI solutions for the Indian market.

For related integrations:

* You can also connect your own Sarvam account and use it with [Bolna AI](https://platform.bolna.ai/auth/sarvam)
