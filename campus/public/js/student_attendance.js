// Student Attendance Form View: Quick access to Class-wise and Batch-wise Attendance entry
frappe.provide("campus");

frappe.ui.form.on("Student Attendance", {
	refresh(frm) {
		frm.add_custom_button(__("Mark Batch Attendance"), () => {
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
		}).addClass("btn-secondary");

		if (frm.is_new()) {
			frm.dashboard.clear_headline();
			frm.dashboard.set_headline(
				__(
					"Need to mark attendance for a whole class or batch? {0}",
					[
						`<button type="button" class="btn btn-xs btn-primary ml-2 font-weight-bold" onclick="campus.show_batch_attendance_dialog({ frm: cur_frm });">${__("Open Class / Batch Attendance Entry")}</button>`,
					]
				),
				"blue"
			);
		}
	},
});
