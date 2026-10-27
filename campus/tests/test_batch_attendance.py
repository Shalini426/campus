"""Tests for class-wise and batch-wise attendance entry workflow (BUG fix)."""

import json

import frappe
from frappe.utils import add_days, today

from campus.student_services.attendance import (
	get_attendance_roll,
	submit_batch_attendance,
)
from campus.tests.utils import CampusTestCase

BATCH_NAME = "TEST-BATCH-ATT-2026"
COURSE_NAME = "TEST-COURSE-ATT"


class TestBatchAttendance(CampusTestCase):
	def setUp(self):
		super().setUp()
		self.cleanup()
		self.setup_test_data()

	def tearDown(self):
		self.cleanup()
		super().tearDown()

	def cleanup(self):
		frappe.db.delete("Student Attendance", {"student_batch": BATCH_NAME})
		frappe.db.delete("Subject Schedule", {"student_batch": BATCH_NAME})
		frappe.db.delete("Course Enrollment", {"student_batch": BATCH_NAME})
		frappe.db.delete("Student", {"email_address": ["like", "%att_student%"]})
		frappe.db.delete("User", {"email": ["like", "%att_student%"]})
		frappe.db.delete("Student Batch Name", {"name": BATCH_NAME})
		frappe.db.delete("Course", {"name": COURSE_NAME})

	def setup_test_data(self):
		from campus.student_services.setup import seed_lifecycle_rules
		seed_lifecycle_rules()

		hl_name = "Test Academic Holidays"
		if not frappe.db.exists("Holiday List", hl_name):
			hl = frappe.get_doc({
				"doctype": "Holiday List",
				"holiday_list_name": hl_name,
				"from_date": add_days(today(), -180),
				"to_date": add_days(today(), 365),
			})
			hl.flags.ignore_mandatory = True
			hl.insert(ignore_permissions=True)

		all_companies = frappe.get_all("Company", pluck="name")
		for comp in all_companies:
			frappe.db.set_value("Company", comp, "default_holiday_list", hl_name)
		if all_companies:
			frappe.db.set_single_value("Global Defaults", "default_company", all_companies[0])
			frappe.db.set_default("company", all_companies[0])

		if not frappe.db.exists("Course", COURSE_NAME):
			c = frappe.get_doc({
				"doctype": "Course",
				"course_name": COURSE_NAME,
				"course_abbreviation": "TATT",
			})
			c.flags.ignore_mandatory = True
			c.insert(ignore_permissions=True)

		if not frappe.db.exists("Student Batch Name", BATCH_NAME):
			b = frappe.get_doc({
				"doctype": "Student Batch Name",
				"batch_name": BATCH_NAME,
				"course": COURSE_NAME,
				"max_strength": 50,
			})
			b.flags.ignore_mandatory = True
			b.insert(ignore_permissions=True)

		self.students = []
		for i in range(1, 4):
			s = frappe.get_doc({
				"doctype": "Student",
				"first_name": f"AttStudent{i}",
				"email_address": f"att_student_{i}_{frappe.generate_hash(length=6)}@example.com",
				"enabled": 1,
			})
			s.flags.ignore_mandatory = True
			s.insert(ignore_permissions=True)
			self.students.append(s.name)

			enrollment = frappe.get_doc({
				"doctype": "Course Enrollment",
				"student": s.name,
				"student_name": f"AttStudent{i}",
				"student_batch": BATCH_NAME,
				"course": COURSE_NAME,
				"roll_number": f"ROLL-{i:02d}",
				"docstatus": 1,
			})
			enrollment.flags.ignore_validate = True
			enrollment.flags.ignore_mandatory = True
			enrollment.insert(ignore_permissions=True)

		schedule = frappe.get_doc({
			"doctype": "Subject Schedule",
			"student_batch": BATCH_NAME,
			"course": COURSE_NAME,
			"schedule_date": today(),
			"from_time": "10:00:00",
			"to_time": "11:00:00",
		})
		schedule.flags.ignore_mandatory = True
		self.schedule = schedule.insert(ignore_permissions=True)

	def test_get_attendance_roll_by_schedule(self):
		"""Roster is fetched automatically with all batch students and default Present status."""
		res = get_attendance_roll(
			based_on="Subject Schedule",
			subject_schedule=self.schedule.name,
		)
		self.assertEqual(res["total"], 3)
		self.assertEqual(len(res["students"]), 3)
		self.assertEqual(res["student_batch"], BATCH_NAME)
		self.assertEqual(res["students"][0]["roll_number"], "ROLL-01")
		self.assertEqual(res["students"][0]["status"], "Present")

	def test_get_attendance_roll_by_batch(self):
		"""Roster is fetched by Student Batch and date."""
		res = get_attendance_roll(
			based_on="Student Batch",
			student_batch=BATCH_NAME,
			date=today(),
		)
		self.assertEqual(res["total"], 3)
		self.assertEqual(res["students"][1]["roll_number"], "ROLL-02")

	def test_submit_batch_attendance_single_submission(self):
		"""All students attendance is recorded in a single submission without individual saves."""
		records = [
			{"student": self.students[0], "student_name": "Student 1", "status": "Present"},
			{"student": self.students[1], "student_name": "Student 2", "status": "Absent"},
			{"student": self.students[2], "student_name": "Student 3", "status": "Present"},
		]
		result = submit_batch_attendance(
			based_on="Subject Schedule",
			records=records,
			subject_schedule=self.schedule.name,
		)
		self.assertTrue(result["success"])
		self.assertEqual(result["total"], 3)
		self.assertEqual(result["present"], 2)
		self.assertEqual(result["absent"], 1)

		# Verify Student Attendance records created
		att1 = frappe.db.get_value(
			"Student Attendance",
			{"student": self.students[0], "subject_schedule": self.schedule.name, "docstatus": 1},
			"status",
		)
		att2 = frappe.db.get_value(
			"Student Attendance",
			{"student": self.students[1], "subject_schedule": self.schedule.name, "docstatus": 1},
			"status",
		)
		self.assertEqual(att1, "Present")
		self.assertEqual(att2, "Absent")

	def test_prevent_duplicate_records_on_resubmission(self):
		"""Submitting again modifies existing records instead of generating duplicates."""
		records = [
			{"student": self.students[0], "student_name": "Student 1", "status": "Present"},
			{"student": self.students[1], "student_name": "Student 2", "status": "Absent"},
			{"student": self.students[2], "student_name": "Student 3", "status": "Present"},
		]
		submit_batch_attendance(
			based_on="Subject Schedule",
			records=records,
			subject_schedule=self.schedule.name,
		)
		initial_count = frappe.db.count("Student Attendance", {"subject_schedule": self.schedule.name, "docstatus": 1})
		self.assertEqual(initial_count, 3)

		# Change student 2 from Absent to Present, and student 1 from Present to Absent
		records[0]["status"] = "Absent"
		records[1]["status"] = "Present"
		second_res = submit_batch_attendance(
			based_on="Subject Schedule",
			records=records,
			subject_schedule=self.schedule.name,
		)
		self.assertEqual(second_res["updated"], 2)

		final_count = frappe.db.count("Student Attendance", {"subject_schedule": self.schedule.name, "docstatus": 1})
		self.assertEqual(final_count, 3, "No duplicate attendance records should be created")

		# Check updated statuses
		new_att1 = frappe.db.get_value(
			"Student Attendance",
			{"student": self.students[0], "subject_schedule": self.schedule.name, "docstatus": 1},
			"status",
		)
		new_att2 = frappe.db.get_value(
			"Student Attendance",
			{"student": self.students[1], "subject_schedule": self.schedule.name, "docstatus": 1},
			"status",
		)
		self.assertEqual(new_att1, "Absent")
		self.assertEqual(new_att2, "Present")

	def test_future_date_rejected(self):
		"""Attendance cannot be marked for future dates."""
		future = add_days(today(), 2)
		records = [{"student": self.students[0], "status": "Present"}]
		with self.assertRaisesRegex(frappe.ValidationError, "future"):
			submit_batch_attendance(
				based_on="Student Batch",
				records=records,
				student_batch=BATCH_NAME,
				date=future,
			)
