"""Class-wise and batch-wise attendance entry service.

Provides a unified, validated single-screen workflow for faculty and academic staff
to record attendance for all students in a scheduled class or batch in a single submission,
preventing duplicate records and enforcing permissions and cut-offs.
"""

import json

import frappe
from frappe import _
from frappe.utils import getdate, today

from campus.faculty import attendance_corrections

ALLOWED_STATUSES = ("Present", "Absent", "Leave")
MANAGING_ROLES = {"Administrator", "System Manager", "Academics User", "Academic Administrator", "HOD", "Dean Academics"}


def check_attendance_permissions(user=None, subject_schedule=None, student_batch=None):
	"""Enforce role-based permissions: Academics staff or the assigned Faculty/Instructor."""
	user = user or frappe.session.user
	if user == "Administrator":
		return True

	user_roles = set(frappe.get_roles(user))
	if user_roles & MANAGING_ROLES:
		return True

	if "Instructor" in user_roles or "Faculty" in user_roles:
		if subject_schedule:
			schedule = frappe.db.get_value(
				"Subject Schedule",
				subject_schedule,
				["faculty", "student_batch"],
				as_dict=True,
			)
			if schedule and schedule.faculty:
				faculty_user = frappe.db.get_value("Faculty", schedule.faculty, "user_id")
				if not faculty_user:
					employee = frappe.db.get_value("Faculty", schedule.faculty, "employee")
					if employee:
						faculty_user = frappe.db.get_value("Employee", employee, "user_id")
				if faculty_user and faculty_user != user:
					# Check substitution
					is_sub = frappe.db.exists(
						"Substitution",
						{
							"course_schedule": subject_schedule,
							"substitute_user": user,
							"status": "Confirmed",
						},
					)
					if not is_sub:
						frappe.throw(
							_("You are only permitted to mark attendance for your own scheduled classes."),
							frappe.PermissionError,
						)
		return True

	frappe.throw(_("You do not have permission to record student attendance."), frappe.PermissionError)


@frappe.whitelist()
def get_attendance_roll(based_on="Subject Schedule", subject_schedule=None, student_batch=None, date=None):
	"""Return student roster and any existing attendance for the class or batch."""
	check_attendance_permissions(subject_schedule=subject_schedule, student_batch=student_batch)

	session_details = {}
	if based_on == "Subject Schedule":
		if not subject_schedule:
			frappe.throw(_("Please select a Scheduled Class / Session."))

		schedule = frappe.db.get_value(
			"Subject Schedule",
			subject_schedule,
			["name", "student_batch", "schedule_date", "course", "subject", "faculty", "room"],
			as_dict=True,
		)
		if not schedule:
			frappe.throw(_("Subject Schedule {0} not found.").format(subject_schedule))

		date = schedule.schedule_date
		student_batch = schedule.student_batch
		session_details = schedule

	if not student_batch:
		frappe.throw(_("No student batch is associated with this session."))

	if not date:
		date = today()

	if getdate(date) > getdate(today()):
		frappe.throw(_("Attendance cannot be marked for future dates."))

	students = fetch_batch_students(student_batch)
	if not students:
		return {
			"students": [],
			"total": 0,
			"session": session_details,
			"date": date,
			"student_batch": student_batch,
			"subject_schedule": subject_schedule,
		}

	student_ids = [s["student"] for s in students]

	# Find existing attendance records for this schedule or batch on this date
	existing_att_map = {}
	att_filters = {
		"student": ["in", student_ids],
		"docstatus": ["!=", 2],
	}
	if subject_schedule:
		att_filters["subject_schedule"] = subject_schedule
	else:
		att_filters["student_batch"] = student_batch
		att_filters["date"] = date
		att_filters["subject_schedule"] = ["in", ("", None)]

	for att in frappe.get_all(
		"Student Attendance",
		filters=att_filters,
		fields=["name", "student", "status", "docstatus"],
		order_by="creation desc",
	):
		if att.student not in existing_att_map:
			existing_att_map[att.student] = att

	# Find approved leave applications covering this date
	_sla_cols = frappe.db.get_table_columns("Student Leave Application") or []
	_leave_fields = ["name", "student", "mark_as_present"]
	# pick the leave-kind label field whichever exists
	for _fld in ("oc_leave_kind", "leave_type"):
		if _fld in _sla_cols:
			_leave_fields.append(_fld)
			break
	leaves = frappe.get_all(
		"Student Leave Application",
		filters={
			"student": ["in", student_ids],
			"docstatus": 1,
			"from_date": ["<=", date],
			"to_date": [">=", date],
		},
		fields=_leave_fields,
	)
	leave_map = {l.student: l for l in leaves}

	roster = []
	for s in students:
		sid = s["student"]
		existing = existing_att_map.get(sid)
		leave = leave_map.get(sid)

		if existing:
			status = existing.status
		elif leave:
			status = "Leave"
		else:
			status = "Present"

		roster.append({
			"student": sid,
			"student_name": s.get("student_name") or sid,
			"roll_number": s.get("roll_number") or "",
			"status": status,
			"existing_id": existing.name if existing else None,
			"has_leave": bool(leave),
			"leave_application": leave.name if leave else None,
		})

	# Sort by roll_number, then student_name
	roster.sort(key=lambda r: (r["roll_number"] or "ZZZZZZ", r["student_name"]))

	return {
		"students": roster,
		"total": len(roster),
		"present_count": sum(1 for r in roster if r["status"] == "Present"),
		"absent_count": sum(1 for r in roster if r["status"] == "Absent"),
		"leave_count": sum(1 for r in roster if r["status"] == "Leave"),
		"already_marked": bool(existing_att_map),
		"session": session_details,
		"date": str(date),
		"student_batch": student_batch,
		"subject_schedule": subject_schedule,
	}


@frappe.whitelist(methods=["POST"])
def submit_batch_attendance(based_on="Subject Schedule", records=None, subject_schedule=None, student_batch=None, date=None):
	"""Save and submit attendance for all students in a batch or scheduled class in one atomic pass."""
	check_attendance_permissions(subject_schedule=subject_schedule, student_batch=student_batch)

	if isinstance(records, str):
		records = json.loads(records)

	if not records:
		frappe.throw(_("No student attendance records provided."))

	if based_on == "Subject Schedule":
		if not subject_schedule:
			frappe.throw(_("Subject Schedule is required."))
		schedule = frappe.db.get_value(
			"Subject Schedule",
			subject_schedule,
			["name", "student_batch", "schedule_date"],
			as_dict=True,
		)
		if not schedule:
			frappe.throw(_("Subject Schedule {0} not found.").format(subject_schedule))
		date = schedule.schedule_date
		student_batch = schedule.student_batch
		if attendance_corrections.past_cutoff(subject_schedule):
			frappe.throw(
				_("Attendance for session {0} is past the {1}-hour cut-off. Please raise an Attendance Correction Request.").format(
					subject_schedule, attendance_corrections.cutoff_hours()
				)
			)
	else:
		if not student_batch:
			frappe.throw(_("Student Batch is required."))
		if not date:
			date = today()
		if attendance_corrections.past_day_cutoff(date):
			frappe.throw(
				_("Attendance for date {0} is past the {1}-hour cut-off. Please raise an Attendance Correction Request.").format(
					date, attendance_corrections.cutoff_hours()
				)
			)

	if getdate(date) > getdate(today()):
		frappe.throw(_("Attendance cannot be marked for future dates."))

	created_count = 0
	updated_count = 0

	for r in records:
		student = r.get("student")
		if not student:
			continue
		status = r.get("status") or "Present"
		if status not in ALLOWED_STATUSES:
			frappe.throw(_("Invalid attendance status: {0}").format(status))

		student_name = r.get("student_name")
		leave_app = r.get("leave_application")

		att_filters = {
			"student": student,
			"docstatus": ["!=", 2],
		}
		if subject_schedule:
			att_filters["subject_schedule"] = subject_schedule
		else:
			att_filters["student_batch"] = student_batch
			att_filters["date"] = date
			att_filters["subject_schedule"] = ["in", ("", None)]

		existing = frappe.get_all(
			"Student Attendance",
			filters=att_filters,
			fields=["name", "status", "docstatus"],
			order_by="creation desc",
		)

		if existing:
			primary = existing[0]
			if primary.status != status:
				doc = frappe.get_doc("Student Attendance", primary.name)
				doc.status = status
				doc.flags.ignore_permissions = True
				doc.flags.attendance_correction = False
				doc.save()
				updated_count += 1
			# Clean up any duplicate records from past buggy submissions
			for dup in existing[1:]:
				if dup.docstatus == 1:
					dup_doc = frappe.get_doc("Student Attendance", dup.name)
					dup_doc.flags.ignore_permissions = True
					dup_doc.cancel()
				elif dup.docstatus == 0:
					frappe.delete_doc("Student Attendance", dup.name, force=1)
		else:
			doc = frappe.new_doc("Student Attendance")
			doc.student = student
			doc.student_name = student_name
			doc.subject_schedule = subject_schedule
			doc.student_batch = student_batch
			doc.date = date
			doc.status = status
			if leave_app:
				doc.leave_application = leave_app
			doc.insert(ignore_permissions=True)
			doc.submit()
			created_count += 1

	return {
		"success": True,
		"total": len(records),
		"created": created_count,
		"updated": updated_count,
		"present": sum(1 for r in records if r.get("status") == "Present"),
		"absent": sum(1 for r in records if r.get("status") == "Absent"),
		"leave": sum(1 for r in records if r.get("status") == "Leave"),
	}


def fetch_batch_students(student_batch):
	"""Retrieve enrolled students from Course Enrollment or Student Group Student."""
	if not student_batch:
		return []

	# Method 1: Course Enrollment (standard Education v17 / OneBook)
	try:
		from education.education.doctype.student_batch_name.student_batch_name import get_batch_students
		students = get_batch_students(student_batch)
		if students:
			return [dict(s) for s in students]
	except Exception:
		pass

	# Method 2: Direct query on Course Enrollment
	if frappe.db.exists("DocType", "Course Enrollment"):
		enrollments = frappe.get_all(
			"Course Enrollment",
			filters={"student_batch": student_batch, "docstatus": 1},
			fields=["student", "student_name", "roll_number"],
		)
		if enrollments:
			return enrollments

	# Method 3: Student Group Student (if Student Group variant)
	if frappe.db.exists("DocType", "Student Group Student"):
		group_students = frappe.get_all(
			"Student Group Student",
			filters={"parent": student_batch, "active": 1},
			fields=["student", "student_name", "group_roll_number as roll_number"],
		)
		if group_students:
			return group_students

	return []
