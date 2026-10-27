// Student Attendance List View enhancements: Class-wise and Batch-wise Attendance entry
frappe.provide("campus");

frappe.listview_settings["Student Attendance"] = frappe.listview_settings["Student Attendance"] || {};

const att_list_onload_before = frappe.listview_settings["Student Attendance"].onload;
frappe.listview_settings["Student Attendance"].onload = function (listview) {
	if (att_list_onload_before) att_list_onload_before(listview);

	listview.page.add_inner_button(__("Mark Attendance"), () => {
		if (campus && campus.show_batch_attendance_dialog) {
			campus.show_batch_attendance_dialog({ listview });
		} else {
			frappe.require("/assets/campus/js/batch_attendance.js", () => {
				campus.show_batch_attendance_dialog({ listview });
			});
		}
	}).addClass("btn-primary");
};
