// Class-wise and Batch-wise Attendance Entry Interface for OneBook Campus
window.campus = window.campus || {};

campus.show_batch_attendance_dialog = function (opts = {}) {
	const dialog = new frappe.ui.Dialog({
		title: __("Mark Class / Batch Attendance"),
		size: "extra-large",
		fields: [
			{
				fieldname: "based_on",
				fieldtype: "Select",
				label: __("Attendance Based On"),
				options: [
					{ label: __("Scheduled Class (Subject Schedule)"), value: "Subject Schedule" },
					{ label: __("Student Batch"), value: "Student Batch" },
				],
				default: opts.subject_schedule ? "Subject Schedule" : "Subject Schedule",
				change() {
					update_field_dependencies();
				},
			},
			{ fieldtype: "Column Break" },
			{
				fieldname: "subject_schedule",
				fieldtype: "Link",
				options: "Subject Schedule",
				label: __("Scheduled Class / Session"),
				depends_on: "eval:doc.based_on == 'Subject Schedule'",
				default: opts.subject_schedule || "",
				get_query() {
					const filters = {
						schedule_date: ["<=", frappe.datetime.get_today()],
					};
					// If logged in as Instructor/Faculty without admin rights, filter by faculty
					const user_roles = frappe.user_roles || [];
					const is_admin =
						user_roles.includes("System Manager") ||
						user_roles.includes("Academics User") ||
						user_roles.includes("Administrator");
					if (!is_admin && user_roles.includes("Faculty")) {
						// filter could be applied if current faculty is known
					}
					return { filters };
				},
				change() {
					const schedule = dialog.get_value("subject_schedule");
					if (schedule) {
						load_schedule_info(schedule);
					}
				},
			},
			{
				fieldname: "student_batch",
				fieldtype: "Link",
				options: "Student Batch Name",
				label: __("Student Batch"),
				depends_on: "eval:doc.based_on == 'Student Batch'",
				default: opts.student_batch || "",
				get_query: () => ({ filters: { disabled: 0 } }),
				change() {
					trigger_load_if_ready();
				},
			},
			{ fieldtype: "Column Break" },
			{
				fieldname: "date",
				fieldtype: "Date",
				label: __("Date"),
				default: frappe.datetime.get_today(),
				depends_on: "eval:doc.based_on == 'Student Batch'",
				change() {
					const d = dialog.get_value("date");
					if (d && d > frappe.datetime.get_today()) {
						frappe.msgprint(__("Attendance cannot be marked for future dates."));
						dialog.set_value("date", frappe.datetime.get_today());
						return;
					}
					trigger_load_if_ready();
				},
			},
			{ fieldtype: "Section Break", label: __("Session Information") },
			{
				fieldname: "session_info_html",
				fieldtype: "HTML",
			},
			{ fieldtype: "Section Break", label: __("Students Roster") },
			{
				fieldname: "students_html",
				fieldtype: "HTML",
			},
		],
		primary_action_label: __("Submit Attendance"),
		primary_action() {
			submit_attendance();
		},
	});

	let current_students = [];

	function update_field_dependencies() {
		const based_on = dialog.get_value("based_on");
		dialog.fields_dict.session_info_html.$wrapper.empty();
		dialog.fields_dict.students_html.$wrapper.empty();
		current_students = [];
		if (based_on === "Subject Schedule") {
			const sched = dialog.get_value("subject_schedule");
			if (sched) load_schedule_info(sched);
		} else {
			trigger_load_if_ready();
		}
	}

	function load_schedule_info(schedule_name) {
		frappe.db.get_value(
			"Subject Schedule",
			schedule_name,
			["name", "student_batch", "schedule_date", "course", "subject", "faculty", "room"],
			(res) => {
				if (!res) return;
				render_session_info({
					course: res.course,
					subject: res.subject,
					batch: res.student_batch,
					date: res.schedule_date,
					room: res.room,
					faculty: res.faculty,
				});
				fetch_roll({
					based_on: "Subject Schedule",
					subject_schedule: schedule_name,
				});
			}
		);
	}

	function trigger_load_if_ready() {
		const batch = dialog.get_value("student_batch");
		const date = dialog.get_value("date");
		if (batch && date) {
			render_session_info({
				batch: batch,
				date: date,
			});
			fetch_roll({
				based_on: "Student Batch",
				student_batch: batch,
				date: date,
			});
		}
	}

	function render_session_info(info) {
		const html = `
			<div class="row text-muted" style="font-size: 13px; margin: 0 4px 12px 4px; padding: 10px; background: var(--bg-light-gray, #f8f9fa); border-radius: 6px;">
				<div class="col-sm-3"><b>${__("Batch")}:</b> ${frappe.utils.escape_html(info.batch || "-")}</div>
				<div class="col-sm-3"><b>${__("Date")}:</b> ${info.date || "-"}</div>
				${info.course ? `<div class="col-sm-3"><b>${__("Course")}:</b> ${frappe.utils.escape_html(info.course)}</div>` : ""}
				${info.subject ? `<div class="col-sm-3"><b>${__("Subject")}:</b> ${frappe.utils.escape_html(info.subject)}</div>` : ""}
				${info.room ? `<div class="col-sm-3"><b>${__("Room")}:</b> ${frappe.utils.escape_html(info.room)}</div>` : ""}
				${info.faculty ? `<div class="col-sm-3"><b>${__("Faculty")}:</b> ${frappe.utils.escape_html(info.faculty)}</div>` : ""}
			</div>
		`;
		dialog.fields_dict.session_info_html.$wrapper.html(html);
	}

	function fetch_roll(args) {
		dialog.fields_dict.students_html.$wrapper.html(`
			<div class="text-center py-5 text-muted">
				<div class="spinner-border spinner-border-sm mr-2" role="status"></div>
				${__("Loading students...")}
			</div>
		`);

		frappe.call({
			method: "campus.student_services.attendance.get_attendance_roll",
			args: args,
			callback: (r) => {
				if (!r.message || !r.message.students || !r.message.students.length) {
					dialog.fields_dict.students_html.$wrapper.html(`
						<div class="text-center py-4 text-muted">
							${__("No students found in the selected batch.")}
						</div>
					`);
					current_students = [];
					return;
				}
				current_students = r.message.students;
				render_students_table(r.message);
			},
		});
	}

	function render_students_table(data) {
		const $wrapper = dialog.fields_dict.students_html.$wrapper;
		$wrapper.empty();

		const $container = $(`
			<div class="batch-attendance-container">
				<div class="d-flex justify-content-between align-items-center mb-3 flex-wrap">
					<div class="status-counts d-flex align-items-center gap-2">
						<span class="badge badge-info mr-2 px-2 py-1 font-weight-bold" style="font-size: 13px;">
							${__("Total")}: <span class="count-total">${data.total}</span>
						</span>
						<span class="badge badge-success mr-2 px-2 py-1 font-weight-bold" style="font-size: 13px;">
							${__("Present")}: <span class="count-present">${data.present_count}</span>
						</span>
						<span class="badge badge-danger mr-2 px-2 py-1 font-weight-bold" style="font-size: 13px;">
							${__("Absent")}: <span class="count-absent">${data.absent_count}</span>
						</span>
						${
							data.leave_count > 0
								? `<span class="badge badge-warning mr-2 px-2 py-1 font-weight-bold" style="font-size: 13px;">
									${__("On Leave")}: <span class="count-leave">${data.leave_count}</span>
								</span>`
								: ""
						}
					</div>
					<div class="bulk-actions d-flex align-items-center gap-2 mt-2 mt-sm-0">
						<input type="text" class="form-control form-control-sm mr-3 student-search-input" placeholder="${__("Search student...")}" style="max-width: 200px;">
						<button type="button" class="btn btn-xs btn-outline-success mr-2 btn-mark-all-present">
							<i class="fa fa-check mr-1"></i>${__("Mark All Present")}
						</button>
						<button type="button" class="btn btn-xs btn-outline-danger btn-mark-all-absent">
							<i class="fa fa-times mr-1"></i>${__("Mark All Absent")}
						</button>
					</div>
				</div>

				<div class="table-responsive" style="max-height: 420px; overflow-y: auto; border: 1px solid var(--border-color, #e2e8f0); border-radius: 6px;">
					<table class="table table-hover table-sm mb-0 student-attendance-grid">
						<thead style="position: sticky; top: 0; background: var(--bg-light-gray, #f8f9fa); z-index: 1;">
							<tr>
								<th style="width: 45px; text-align: center;">#</th>
								<th style="width: 140px;">${__("Roll Number")}</th>
								<th>${__("Student Name")}</th>
								<th style="width: 220px; text-align: center;">${__("Attendance Status")}</th>
							</tr>
						</thead>
						<tbody></tbody>
					</table>
				</div>
			</div>
		`).appendTo($wrapper);

		const $tbody = $container.find("tbody");

		data.students.forEach((student, idx) => {
			const is_present = student.status === "Present";
			const is_absent = student.status === "Absent";
			const is_leave = student.status === "Leave";

			const $row = $(`
				<tr class="student-row" data-student="${student.student}">
					<td style="text-align: center; color: var(--text-muted);">${idx + 1}</td>
					<td class="font-weight-bold student-roll">${frappe.utils.escape_html(student.roll_number || "-")}</td>
					<td class="student-name-col">
						<div class="font-weight-medium">${frappe.utils.escape_html(student.student_name)}</div>
						<div class="text-muted small">${student.student}</div>
					</td>
					<td style="text-align: center;">
						<div class="btn-group btn-group-sm btn-group-toggle" role="group">
							<button type="button" class="btn btn-status-present ${is_present ? "btn-success active text-white" : "btn-default"}" data-status="Present" style="min-width: 80px;">
								<i class="fa fa-check mr-1"></i>${__("Present")}
							</button>
							<button type="button" class="btn btn-status-absent ${is_absent ? "btn-danger active text-white" : "btn-default"}" data-status="Absent" style="min-width: 80px;">
								<i class="fa fa-times mr-1"></i>${__("Absent")}
							</button>
						</div>
						${
							student.has_leave
								? `<div class="mt-1"><span class="badge badge-warning" title="${__("Approved Leave Application")}"><i class="fa fa-calendar-check-o mr-1"></i>${__("Approved Leave")}</span></div>`
								: ""
						}
					</td>
				</tr>
			`);

			$tbody.append($row);
		});

		// Status Toggle Handler
		$tbody.on("click", ".btn-status-present, .btn-status-absent", function () {
			const $btn = $(this);
			const new_status = $btn.data("status");
			const $row = $btn.closest("tr");
			const student_id = $row.data("student");

			const item = current_students.find((s) => s.student === student_id);
			if (item) {
				item.status = new_status;
			}

			const $present_btn = $row.find(".btn-status-present");
			const $absent_btn = $row.find(".btn-status-absent");

			if (new_status === "Present") {
				$present_btn.removeClass("btn-default").addClass("btn-success active text-white");
				$absent_btn.removeClass("btn-danger active text-white").addClass("btn-default");
			} else {
				$absent_btn.removeClass("btn-default").addClass("btn-danger active text-white");
				$present_btn.removeClass("btn-success active text-white").addClass("btn-default");
			}

			update_summary_counts();
		});

		// Mark All Present
		$container.find(".btn-mark-all-present").on("click", function () {
			current_students.forEach((s) => {
				s.status = "Present";
			});
			$tbody.find(".student-row").each(function () {
				const $r = $(this);
				$r.find(".btn-status-present").removeClass("btn-default").addClass("btn-success active text-white");
				$r.find(".btn-status-absent").removeClass("btn-danger active text-white").addClass("btn-default");
			});
			update_summary_counts();
		});

		// Mark All Absent
		$container.find(".btn-mark-all-absent").on("click", function () {
			current_students.forEach((s) => {
				s.status = "Absent";
			});
			$tbody.find(".student-row").each(function () {
				const $r = $(this);
				$r.find(".btn-status-absent").removeClass("btn-default").addClass("btn-danger active text-white");
				$r.find(".btn-status-present").removeClass("btn-success active text-white").addClass("btn-default");
			});
			update_summary_counts();
		});

		// Filter students in real time
		$container.find(".student-search-input").on("input", function () {
			const query = $(this).val().toLowerCase().trim();
			$tbody.find(".student-row").each(function () {
				const $r = $(this);
				const text = $r.text().toLowerCase();
				$r.toggle(text.includes(query));
			});
		});
	}

	function update_summary_counts() {
		const total = current_students.length;
		const present = current_students.filter((s) => s.status === "Present").length;
		const absent = current_students.filter((s) => s.status === "Absent").length;
		const leave = current_students.filter((s) => s.status === "Leave").length;

		dialog.fields_dict.students_html.$wrapper.find(".count-total").text(total);
		dialog.fields_dict.students_html.$wrapper.find(".count-present").text(present);
		dialog.fields_dict.students_html.$wrapper.find(".count-absent").text(absent);
		dialog.fields_dict.students_html.$wrapper.find(".count-leave").text(leave);
	}

	function submit_attendance() {
		if (!current_students || !current_students.length) {
			frappe.msgprint(__("No students loaded to mark attendance."));
			return;
		}

		const based_on = dialog.get_value("based_on");
		const subject_schedule = dialog.get_value("subject_schedule");
		const student_batch = dialog.get_value("student_batch");
		const date = dialog.get_value("date");

		const total = current_students.length;
		const present = current_students.filter((s) => s.status === "Present").length;
		const absent = current_students.filter((s) => s.status === "Absent").length;

		frappe.confirm(
			__(
				"Submit attendance for <b>{0}</b> students?<br><br><span class='text-success font-weight-bold'>Present: {1}</span> &nbsp;|&nbsp; <span class='text-danger font-weight-bold'>Absent: {2}</span>",
				[total, present, absent]
			),
			() => {
				frappe.call({
					method: "campus.student_services.attendance.submit_batch_attendance",
					freeze: true,
					freeze_message: __("Recording attendance..."),
					args: {
						based_on: based_on,
						records: JSON.stringify(current_students),
						subject_schedule: subject_schedule,
						student_batch: student_batch,
						date: date,
					},
					callback(r) {
						if (r.message && r.message.success) {
							frappe.show_alert({
								message: __(
									"Attendance saved successfully: {0} Present, {1} Absent",
									[r.message.present, r.message.absent]
								),
								indicator: "green",
							});
							dialog.hide();
							if (opts.listview) {
								opts.listview.refresh();
							} else if (opts.frm) {
								opts.frm.reload_doc();
							}
						}
					},
				});
			}
		);
	}

	dialog.show();

	// If initial options provided, trigger initial selection
	if (opts.subject_schedule) {
		dialog.set_value("based_on", "Subject Schedule");
		dialog.set_value("subject_schedule", opts.subject_schedule);
	} else if (opts.student_batch) {
		dialog.set_value("based_on", "Student Batch");
		dialog.set_value("student_batch", opts.student_batch);
	}
};
