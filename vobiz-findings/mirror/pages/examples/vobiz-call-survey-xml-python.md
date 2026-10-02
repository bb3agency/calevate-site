> ## Documentation Index
> Fetch the complete documentation index at: https://www.vobiz.ai/docs/llms.txt
> Use this file to discover all available pages before exploring further.

# Call survey

> Run an outbound three-question DTMF voice survey on Vobiz, store results via the API, and export responses to CSV - complete Python and XML example.

Outbound 3-question DTMF survey with results API and CSV export.

**XML elements used:** `<Speak>`, `<Gather inputType=dtmf numDigits=1>`, `<Redirect>`, `<Hangup>`

<Card title="View on GitHub" icon="github" href="https://github.com/vobiz-ai/Vobiz-Call-Survey-XML-Python">
  Clone and run the full working example
</Card>

## Getting started

```bash theme={null}
git clone https://github.com/vobiz-ai/Vobiz-Call-Survey-XML-Python.git
cd Vobiz-Call-Survey-XML-Python
cp .env.example .env
pip install -r requirements.txt
python server.py
```

## Overview

Your system triggers an outbound survey call to a phone number. The caller answers three DTMF questions in sequence - rating (1–5), recommendation (yes/no), and overall experience (1–3). All responses are stored and exportable as CSV. You can also view aggregated stats via the API.

## Call flow

```text theme={null}
Your system
  └── POST /surveys/trigger {"phone": "+91XXXXXXXXXX"}
        └── Vobiz outbound call triggered
              └── /answer  → Survey intro
                    └── /survey-q1  → "Rate our service: press 1 (poor) to 5 (excellent)"
                          └── /survey-q1-result  → Saves Q1 → routes to Q2
                                └── /survey-q2  → "Would you recommend us? Press 1=Yes, 2=No"
                                      └── /survey-q2-result  → Saves Q2 → routes to Q3
                                            └── /survey-q3  → "Overall experience: 1=Good, 2=Neutral, 3=Poor"
                                                  └── /survey-q3-result  → Saves Q3 → done
                                                        └── /survey-done  → "Thank you!" → Hangup

  └── GET /surveys/summary   → aggregated results
  └── GET /surveys/export.csv → download all responses
```

## Vobiz webhooks

Set `/answer` as the **Answer URL** in your Vobiz application.

| Method | Path | Description |
| - | - | - |
| POST | `/answer` | Survey intro |
| POST | `/survey-q1` | Q1: rate service 1–5 |
| POST | `/survey-q1-result` | Saves Q1 → routes to Q2 |
| POST | `/survey-q2` | Q2: recommend yes/no |
| POST | `/survey-q2-result` | Saves Q2 → routes to Q3 |
| POST | `/survey-q3` | Q3: overall experience |
| POST | `/survey-q3-result` | Saves Q3 → routes to done |
| POST | `/survey-done` | Finalizes survey, logs full result |
| POST | `/hangup` | Cleanup |

## App API

| Method | Path | Description |
| - | - | - |
| POST | `/surveys/trigger` | Trigger a survey call |
| GET | `/surveys/results` | List all completed responses |
| GET | `/surveys/results/{id}` | Single response detail |
| GET | `/surveys/export.csv` | Download all results as CSV |
| GET | `/surveys/summary` | Aggregated stats |

## Environment variables

| Variable | Required | Description |
| - | - | - |
| `VOBIZ_AUTH_ID` | Yes | Vobiz account auth ID |
| `VOBIZ_AUTH_TOKEN` | Yes | Vobiz account auth token |
| `FROM_NUMBER` | Yes | Your Vobiz DID |
| `HTTP_PORT` | No | Server port (default: 8000) |
| `PUBLIC_URL` | No | Production URL - skips ngrok if set |
| `NGROK_AUTH_TOKEN` | No | ngrok auth token for local dev |


This documentation is built and hosted on [Mintlify](https://mintlify.com), a developer documentation platform.