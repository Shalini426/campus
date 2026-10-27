// Student Attendance Tool integration
frappe.provide("campus");

frappe.ui.form.on("Student Attendance Tool", {
	refresh(frm) {
		frm.disable_save();
		frm.add_custom_button(__("Open Attendance Entry"), () => {
			if (campus && campus.show_batch_attendance_dialog) {
				campus.show_batch_attendance_dialog({
					frm: frm,
					subject_schedule: frm.doc.subject_schedule,
					student_batch: frm.doc.student_batch,
				});
			} else {
				frappe.require("/assets/campus/js/batch_attendance.js", () => {
					campus.show_batch_attendance_dialog({
						frm: frm,
						subject_schedule: frm.doc.subject_schedule,
						student_batch: frm.doc.student_batch,
					});
				});
			}
		}).addClass("btn-primary");
	},
});
