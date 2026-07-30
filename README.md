# Microgrid Feasibility Dashboard

This project is a Microgrid Feasibility Dashboard, consisting of a Python Flask backend API and a React frontend.

## Prerequisites

- Node.js
- npm
- Python 3.x
- pip

## How to Run the Program

You need to run both the backend (Flask) and the frontend (React) servers simultaneously in two separate terminal windows.

### 1. Run the Backend (Flask API)

Open a terminal in the root directory of this repository and run the following commands:

`pip install -r requirements.txt`

`python app.py`

The backend server should now be running, typically on `http://127.0.0.1:5000`.

### 2. Run the Frontend (React App)

Open a **new, second terminal window**, also in the root directory of this repository, and run:

`npm install`

`npm start` (Assuming you map this to react-scripts start or similar, otherwise just the regular start command)
