# Virtual Career Counselor (Flask + AWS) - Demo

This repository contains a minimal Flask-based prototype of the "Virtual Career Counselor" described in the requirements. It includes a simple UI, local fallback storage, and AWS integration points (DynamoDB and SNS) with mock behavior when AWS is not configured.

## Features

### User Features
- **Career Exploration**: Explore ANY profession worldwide (including specialized ones like CA, IAS, etc.)
- **Personalized Roadmaps**: AI-generated learning paths for any career
- **Course Recommendations**: Get 10-15 comprehensive course recommendations based on your career goals
- **Job Market Insights**: Real-time market trends, salary data, and job availability
- **Real Job Listings**: Browse and apply to real job postings from admins
- **Activity Tracking**: Track your learning progress with quizzes and activities
- **Leaderboard**: See how you rank among other users

### Admin Features
- **Admin Dashboard**: Manage job postings and applications
- **Job Posting**: Post job opportunities with detailed requirements
- **Application Management**: Review, accept, reject, or schedule interviews for applicants
- **Real-time Updates**: See all applications in real-time

## Quick Start

1. Create and activate a Python virtual environment.

```bash
python -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt
```

2. Set up environment variables (optional for AWS integration):

Create a `.env` file with:
```
GROQ_API_KEY=your_groq_api_key_here
FLASK_SECRET=your_secret_key_here
```

3. Create an admin account (optional):

```bash
python create_admin.py
```

4. Run the app

```bash
python app.py
```

Open http://localhost:5000

## Configuration

- `GROQ_API_KEY`: API key for Groq (used for AI-powered features)
- `AWS_REGION`, `DDB_TABLE`, `SNS_TOPIC_ARN` for DynamoDB and SNS integration
- `FLASK_SECRET`: Secret key for Flask sessions

## Usage

### For Users
1. Sign up or login at `/login`
2. Explore careers at `/career-explore` - Enter ANY profession (e.g., "CA", "Teacher", "Software Engineer")
3. View courses at `/courses` - Enter a profession to see all related courses
4. Browse jobs at `/job-insights` - See real job postings and apply
5. Track progress at `/dashboard`

### For Admins
1. Login at `/admin/login`
2. Post jobs at `/admin/jobs`
3. Manage applications at `/admin/applications`
4. View dashboard at `/admin/dashboard`

## Notes

- This is a demo scaffold. The AI call path is intentionally tolerant: if Groq or DynamoDB are not available, the app uses a local JSON store at `data/store.json` and a mocked generator.
- Career exploration now works for ANY profession globally, including specialized ones like CA (Chartered Accountant), IAS (Indian Administrative Service), etc.
- Course recommendations show 10-15 comprehensive courses from real platforms (Coursera, Udemy, edX, etc.)
- Job postings are real and managed by admins - users can apply directly through the platform
- For production, replace mock logic with secure, authenticated AI invocations, hardened IAM roles, and proper IaC.
