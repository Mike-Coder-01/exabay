# Project Installation and Setup Guide

## 1. Project Overview

This project is a Django-based web application that uses PostgreSQL as its database and Docker for containerized development and deployment.

This guide explains how to set up and run the project on a new computer.

---

## 2. Prerequisites

Before starting, make sure the following software is installed:

* [ ] Git
* [ ] Docker Desktop
* [ ] Docker Compose
* [ ] A web browser

### Verify the installations

Open a terminal and run:

```bash
git --version
docker --version
docker compose version
```

If these commands return version numbers, the required tools are installed correctly.

---

## 3. Clone the Project

Open a terminal and navigate to the directory where you want to keep the project.

Clone the GitHub repository:

```bash
git clone git@github.com:Mike-Coder-01/exabay.git
```

Move into the project directory:

```bash
cd exabay
```

---

## 4. Configure Environment Variables

The project uses environment variables for configuration such as database credentials, Django settings, secret keys, and other sensitive information.

Create a `.env` file in the project root directory.

Example:

```env
DEBUG=True

SECRET_KEY=your-secret-key

POSTGRES_DB=your_database_name
POSTGRES_USER=your_database_user
POSTGRES_PASSWORD=your_database_password
POSTGRES_HOST=db
POSTGRES_PORT=5432
```

---

## 5. Build the Docker Containers

From the project root directory, run:

```bash
docker compose build
```

This builds the Docker images required by the application.

---

## 6. Start the Application

Start the containers using:

```bash
docker compose up -d
```

The `-d` option runs the containers in the background.

Check that the containers are running:

```bash
docker compose ps
```

You should see the application and database containers running.

---

## 7. Run Database Migrations

After starting the containers, run Django migrations:

```bash
docker compose exec web python manage.py migrate
```

This creates the required database tables in PostgreSQL.

---

## 8. Create a Superuser

To access the Django administration panel, create a superuser:

```bash
docker compose exec web python manage.py createsuperuser
```

Follow the instructions in the terminal to enter:

* Username or email
* Email address, if required
* Password

---

## 9. Collect Static Files

Run:

```bash
docker compose exec web python manage.py collectstatic --noinput
```

This collects the project's static files into the configured static directory.

---

## 10. Access the Application

Once the containers are running, open a web browser and visit:

```text
http://localhost:8000
```

The Django administration panel can normally be accessed at:

```text
http://localhost:8000/admin/
```

---

## 11. Viewing Application Logs

To view logs from all containers:

```bash
docker compose logs
```

To continuously monitor the logs:

```bash
docker compose logs -f
```

To view logs for only the Django application:

```bash
docker compose logs -f web
```

To stop monitoring the logs, press:

```text
Ctrl + C
```

---

## 12. Stopping the Application

To stop the containers without removing them:

```bash
docker compose stop
```

To stop and remove the containers:

```bash
docker compose down
```

The PostgreSQL data should remain available if the project is configured with a Docker volume for the database.

---

## 13. Restarting the Application

If the containers have already been created, start them again with:

```bash
docker compose start
```

Alternatively:

```bash
docker compose up -d
```

---

## 14. Updating the Project

When new changes are pushed to GitHub, pull the latest version:

```bash
git pull origin main
```

Then rebuild the containers if the dependencies or Docker configuration have changed:

```bash
docker compose build
```

Start the updated application:

```bash
docker compose up -d
```

Run any new migrations:

```bash
docker compose exec web python manage.py migrate
```

If static files have changed:

```bash
docker compose exec web python manage.py collectstatic --noinput
```

---

## 15. Database Backup and Restore

If an existing PostgreSQL database needs to be restored, use the provided database backup file.

A PostgreSQL backup can be restored using:

```bash
docker compose exec -T db psql -U YOUR_POSTGRES_USER -d YOUR_POSTGRES_DB < backup.sql
```

Replace:

```text
YOUR_POSTGRES_USER
YOUR_POSTGRES_DB
```

with the values configured in the `.env` file.

> Make sure the PostgreSQL container is running before performing the restore.

---

## 16. Common Problems

### Port 8000 is already in use

If you receive an error indicating that port `8000` is already being used, either stop the application using that port or change the port mapping in `docker-compose.yml`.

For example:

```yaml
ports:
  - "8001:8000"
```

You would then access the application at:

```text
http://localhost:8001
```

---

### Database connection error

Check that:

1. The PostgreSQL container is running.
2. The database credentials in `.env` are correct.
3. `POSTGRES_HOST` matches the PostgreSQL Docker service name.

For Docker Compose, the database host is normally the service name, for example:

```env
POSTGRES_HOST=db
```

Do not normally use `localhost` as the database host from inside the Django container.

---

### Migration error

Run:

```bash
docker compose exec web python manage.py makemigrations
docker compose exec web python manage.py migrate
```

Only create new migrations when the Django models have actually changed.

---

### Container is not running

Check the container status:

```bash
docker compose ps
```

Then inspect the logs:

```bash
docker compose logs
```

For a specific service:

```bash
docker compose logs web
```

---

## 17. Useful Docker Commands

### Start containers

```bash
docker compose up -d
```

### Stop containers

```bash
docker compose stop
```

### Stop and remove containers

```bash
docker compose down
```

### Rebuild containers

```bash
docker compose build
```

### Rebuild and start

```bash
docker compose up -d --build
```

### View running containers

```bash
docker compose ps
```

### View logs

```bash
docker compose logs -f
```

### Open a Django shell

```bash
docker compose exec web python manage.py shell
```

### Run Django management commands

```bash
docker compose exec web python manage.py COMMAND
```

---

## 18. Project Structure

A typical project structure is:

```text
exabay/
│
├── Dockerfile
├── docker-compose.yml
├── requirements.txt
├── .env
├── .env.example
├── manage.py
│
├── project/
│   ├── settings.py
│   ├── urls.py
│   ├── wsgi.py
│   └── ...
│
├── app/
│   ├── models.py
│   ├── views.py
│   ├── urls.py
│   ├── forms.py
│   └── ...
│
├── static/
├── media/
└── README.md
```

The exact structure may differ depending on the project.

---

## 19. Quick Setup

For an experienced developer, the basic setup is:

```bash
git clone git@github.com:Mike-Coder-01/exabay.git
cd exabay

# Create/configure .env

docker compose build
docker compose up -d

docker compose exec web python manage.py migrate
docker compose exec web python manage.py collectstatic --noinput
docker compose exec web python manage.py createsuperuser
```

Then open:

```text
http://localhost:8000
```

---

## 21. Support

If you encounter an installation problem, first check:

```bash
docker compose ps
```

and:

```bash
docker compose logs
```

These commands usually provide the information needed to identify the problem.
