import re
import tempfile
import unittest
from pathlib import Path

from app import create_app


class JobPortalTests(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.app = create_app(
            {
                "TESTING": True,
                "SECRET_KEY": "test-secret",
                "DATABASE": str(Path(self.temp_dir.name) / "test.sqlite3"),
            }
        )
        self.client = self.app.test_client()

    def tearDown(self):
        self.temp_dir.cleanup()

    def token(self, client, path):
        response = client.get(path)
        self.assertEqual(response.status_code, 200)
        match = re.search(r'name="csrf_token" value="([^"]+)"', response.get_data(as_text=True))
        self.assertIsNotNone(match)
        return match.group(1)

    def register(self, client, role, email, name, company=""):
        token = self.token(client, "/register")
        return client.post(
            "/register",
            data={
                "csrf_token": token,
                "name": name,
                "email": email,
                "password": "a-long-test-password",
                "role": role,
                "company": company,
            },
            follow_redirects=True,
        )

    def test_seeded_jobs_can_be_filtered(self):
        response = self.client.get("/?category=Engineering&location=Remote")
        self.assertEqual(response.status_code, 200)
        page = response.get_data(as_text=True)
        self.assertIn("Backend Engineer, Platform", page)
        self.assertNotIn("Senior Product Designer", page)

    def test_employer_posts_and_seeker_applies(self):
        employer = self.app.test_client()
        self.register(employer, "employer", "team@example.test", "Team Lead", "Acme Works")
        token = self.token(employer, "/employer/jobs/new")
        response = employer.post(
            "/employer/jobs/new",
            data={
                "csrf_token": token,
                "title": "Research Engineer",
                "location": "Remote",
                "category": "Engineering",
                "employment_type": "Full-time",
                "salary": "$120k – $150k",
                "description": "Build useful things with a thoughtful team.",
            },
            follow_redirects=True,
        )
        self.assertEqual(response.status_code, 200)
        self.assertIn(b"Research Engineer", response.data)

        seeker = self.app.test_client()
        self.register(seeker, "seeker", "person@example.test", "Jordan Person")
        with self.app.app_context():
            from app import get_db

            job_id = get_db().execute(
                "SELECT id FROM jobs WHERE title = ?", ("Research Engineer",)
            ).fetchone()["id"]
        detail = f"/jobs/{job_id}"
        token = self.token(seeker, detail)
        response = seeker.post(
            f"{detail}/apply",
            data={"csrf_token": token, "cover_letter": "This role is a strong fit for my experience."},
            follow_redirects=True,
        )
        self.assertEqual(response.status_code, 200)
        self.assertIn(b"Application sent.", response.data)
        self.assertIn(b"You're in the running", response.data)
        employer_page = employer.get("/employer").data
        self.assertIn(b"<strong>1</strong><span>applicant</span>", employer_page)

    def test_csrf_and_role_boundaries(self):
        self.register(self.client, "seeker", "reader@example.test", "Case Reader")
        self.assertEqual(self.client.post("/employer/jobs/new").status_code, 400)
        self.assertEqual(self.client.get("/employer").status_code, 403)


if __name__ == "__main__":
    unittest.main()