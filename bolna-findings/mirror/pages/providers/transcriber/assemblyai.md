> ## Documentation Index
> Fetch the complete documentation index at: https://www.bolna.ai/docs/llms.txt
> Use this file to discover all available pages before exploring further.

# AssemblyAI Transcriber (Speech to Text)

> Integrate AssemblyAI with your Bolna Voice AI agents for accurate English transcription with Universal model and real-time streaming.

## 1. What is AssemblyAI STT?

[AssemblyAI](https://www.assemblyai.com/) Speech-to-Text (STT) is an advanced automatic speech recognition platform that uses AI to transcribe spoken English into text with high accuracy. AssemblyAI provides real-time streaming transcription with their Universal model.

AssemblyAI is designed for enterprise-grade applications requiring accurate English transcription with features like speaker diarization, turn-based conversation management, and customizable confidence thresholds, making it ideal for voice agents, customer support systems, and conversational AI applications.

## 2. Key Features of AssemblyAI STT

AssemblyAI offers comprehensive features for enterprise speech recognition:

* **Universal Model**: High-accuracy English speech recognition model with enterprise-grade performance.

* **Real-Time Streaming**: WebSocket-based streaming API with immutable transcripts and turn-based transcription for voice agent applications.

* **Speaker Diarization**: Identify and separate different speakers in English audio streams.

* **Turn-Based Transcription**: Provides speaking turns with unique identifiers, word-level metadata, and configurable silence detection.

* **High Accuracy**: English transcription with enterprise-grade accuracy and low word error rates.

* **Format Flexibility**: Supports PCM16 and Mu-law encoding with configurable sample rates for different telephony providers.

* **Enterprise Features**: Batch and real-time processing, custom vocabulary, confidence scoring, and detailed analytics.

## 3. How Bolna Uses AssemblyAI for STT

Bolna AI integrates AssemblyAI's STT technology to enable accurate multilingual transcription for voice agents. Here's how Bolna leverages AssemblyAI:

* **Real-Time Voice Processing**:
  Bolna uses AssemblyAI's streaming WebSocket API (v3) to convert spoken language into text in real time. The immutable transcript feature ensures stable text progression without overwrites.

* **English Voice Agent Support**:
  Bolna voice agents use AssemblyAI's streaming API for real-time English transcription with high accuracy and low latency.

* **Turn-Based Conversation Management**:
  Bolna leverages AssemblyAI's turn-based transcription to structure conversations, with each speaking turn having unique identifiers for better context management and response generation.

* **Telephony Provider Optimization**:
  Bolna automatically configures audio encoding (Mu-law for Twilio, Linear16 for others) and sample rates (8kHz for telephony, 16kHz for web) based on the provider.

* **Streaming and Batch Processing**:
  Bolna supports both real-time streaming for live conversations and batch processing for recorded calls, using AssemblyAI's HTTP API for non-streaming scenarios.

* **Enterprise-Grade Reliability**:
  Bolna uses AssemblyAI's enterprise features including automatic language detection, confidence thresholds, and detailed latency tracking for production voice applications.

## 4. List of AssemblyAI models supported on Bolna AI

| Model     |
| --------- |
| universal |

## 5. Supported Languages

For real-time voice agents, AssemblyAI streaming supports:

* **English** - en

## Conclusion

AssemblyAI's STT capabilities empower Bolna AI to deliver highly accurate, real-time English speech-to-text transcription for voice agents. By integrating AssemblyAI's streaming technology, Bolna provides turn-based conversation management, immutable transcripts, and enterprise-grade reliability for production voice AI applications.
