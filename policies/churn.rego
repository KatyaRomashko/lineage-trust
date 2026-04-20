package churn

# Default deny — all allow decisions must be explicit.
default allow := false

# Example policy (user-specified):
# Agent may modify "Original_Date" only if Regional_Policy is not EU
# AND the change is within a 24-hour deviation.
allow {
	input.action == "modify_original_date"
	input.regional_policy != "EU"
	input.hours_deviation <= 24
}
