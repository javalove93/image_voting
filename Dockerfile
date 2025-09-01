# Use the official Python image as a base image
FROM python:3.9-slim-buster

# Set the working directory in the container
WORKDIR /app

# Copy the requirements file into the container
COPY requirements.txt .
COPY sa-key-251130-exp.json .
COPY .env .

# Install any needed packages specified in requirements.txt
RUN pip install --no-cache-dir -r requirements.txt

# Copy the rest of the application code into the container
COPY . .

# Expose the port that the application will listen on
# Cloud Run typically expects applications to listen on port 8080
ENV PORT 8080
EXPOSE $PORT
ENV GOOGLE_APPLICATION_CREDENTIALS /app/sa-key-251130-exp.json

# Run the application using Gunicorn with 1 worker and 5 threads to match Cloud Run's concurrency
# Assuming app.py contains the Flask application instance named 'app'
CMD gunicorn --workers 1 --threads 5 --bind 0.0.0.0:$PORT app:app
