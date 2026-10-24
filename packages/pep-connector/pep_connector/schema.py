"""PEP reservation export columns. Output is always the 66-column v2 layout."""

from __future__ import annotations

from pep_connector.assemble import CODE, CONFIRMATION, COUNT, DATE, MONEY, TIME, Layout, optional, required

V1_COLUMN_COUNT = 63
V2_COLUMN_COUNT = 66

V1_DISPLAY_HEADERS = [
    "Market Segment Code",
    "Local Market Segment Code",
    "Confirmation Number",
    "Group Number",
    "Group Code",
    "External Confirmation Number",
    "PO Number",
    "OTA Booking Number",
    "Package",
    "Status",
    "Guest Name",
    "Contact Role",
    "ADDN GUESTS",
    "HONORS TIER",
    "VIP Level",
    "Requires Assistance",
    "Room Type",
    "Room Number",
    "Rate Plan",
    "Source",
    "Travel Agent Name",
    "Source Code",
    "Complimentary",
    "Market Segment",
    "Local Market Segment",
    "Company Name",
    "Booking Date",
    "Booking Time",
    "Cancellation Date",
    "Cancellation Time",
    "Arrival Date",
    "Arrival Time",
    "Departure Date",
    "Departure time",
    "Nights",
    "Adults",
    "CHILDREN",
    "Guarantee Type",
    "Total Charges",
    "Total Room Revenue",
    "Total Taxes",
    "Total Payments",
    "Balance",
    "Booking Remarks",
    "Stay Remarks",
    "Housekeeping Remarks",
    "Billing Remarks",
    "Other Remarks",
    "DK",
    "Digital Check In",
    "Digital Check Out",
    "Virtual CC",
    "Local First Name",
    "Local Last Name",
    "Average Room Rate",
    "Booked By",
    "Stay Requests",
    "Linked Reservations",
    "Travel Agent Number",
    "Package Name",
    "Package Element",
    "Sub Source Code",
    "Sub Source Name",
]

V2_DISPLAY_HEADERS = [
    "Market Segment Code",
    "Local Market Segment Code",
    "Confirmation Number",
    "Group Number",
    "Group Code",
    "External Confirmation Number",
    "PO Number",
    "OTA Booking Number",
    "Package",
    "Status",
    "Guest Name",
    "First Name",
    "Last Name",
    "Contact Role",
    "ADDN GUESTS",
    "HONORS TIER",
    "VIP Level",
    "Requires Assistance",
    "Room Type",
    "Room Number",
    "Rate Plan",
    "Source",
    "Travel Agent Name",
    "Source Code",
    "Complimentary",
    "Market Segment",
    "Local Market Segment",
    "Company Name",
    "Booking Date",
    "Booking Time",
    "Cancellation Date",
    "Cancellation Time",
    "Cancellation Deadline",
    "Arrival Date",
    "Arrival Time",
    "Departure Date",
    "Departure time",
    "Nights",
    "Adults",
    "CHILDREN",
    "Guarantee Type",
    "Total Charges",
    "Total Room Revenue",
    "Total Taxes",
    "Total Payments",
    "Balance",
    "Booking Remarks",
    "Stay Remarks",
    "Housekeeping Remarks",
    "Billing Remarks",
    "Other Remarks",
    "DK",
    "Digital Check In",
    "Digital Check Out",
    "Virtual CC",
    "Local First Name",
    "Local Last Name",
    "Average Room Rate",
    "Booked By",
    "Stay Requests",
    "Linked Reservations",
    "Travel Agent Number",
    "Package Name",
    "Package Element",
    "Sub Source Code",
    "Sub Source Name",
]

HEADERS = [
    "market_segment_code",
    "local_market_segment_code",
    "confirmation_number",
    "group_number",
    "group_code",
    "external_confirmation_number",
    "po_number",
    "ota_booking_number",
    "package",
    "status",
    "guest_name",
    "first_name",
    "last_name",
    "contact_role",
    "addn_guests",
    "honors_tier",
    "vip_level",
    "requires_assistance",
    "room_type",
    "room_number",
    "rate_plan",
    "source",
    "travel_agent_name",
    "source_code",
    "complimentary",
    "market_segment",
    "local_market_segment",
    "company_name",
    "booking_date",
    "booking_time",
    "cancellation_date",
    "cancellation_time",
    "cancellation_deadline",
    "arrival_date",
    "arrival_time",
    "departure_date",
    "departure_time",
    "nights",
    "adults",
    "children",
    "guarantee_type",
    "total_charges",
    "total_room_revenue",
    "total_taxes",
    "total_payments",
    "balance",
    "booking_remarks",
    "stay_remarks",
    "housekeeping_remarks",
    "billing_remarks",
    "other_remarks",
    "dk",
    "digital_check_in",
    "digital_check_out",
    "virtual_cc",
    "local_first_name",
    "local_last_name",
    "average_room_rate",
    "booked_by",
    "stay_requests",
    "linked_reservations",
    "travel_agent_number",
    "package_name",
    "package_element",
    "sub_source_code",
    "sub_source_name",
]

OUTPUT_HEADERS = [
    *HEADERS,
    "source_file",
    "source_line",
    "parse_status",
    "heal_action",
    "range_start",
    "range_end",
]

SPAN_FIELDS = ("booking_date", "cancellation_date", "arrival_date", "departure_date")

SECTION_HEADER_PREFIX = '"Market Segment Code","Local Market Segment Code","Confirmation Number"'

# Typed columns of the reservation export (display header, lowercased). The formats are
# PEP's own, so they hold for every property; any other column is text. Every
# reservation carries the required ones (only a totals line leaves them blank), which
# is what lets a split row be realigned without guessing.
RESERVATION_TYPES = {
    "market segment code": required(CODE),
    "local market segment code": optional(CODE),
    "confirmation number": required(CONFIRMATION),
    "booking date": required(DATE),
    "booking time": required(TIME),
    "cancellation date": optional(DATE),
    "cancellation time": optional(TIME),
    "arrival date": required(DATE),
    "departure date": required(DATE),
    "nights": required(COUNT),
    "adults": required(COUNT),
    "children": required(COUNT),
    "total charges": required(MONEY),
    "total room revenue": required(MONEY),
    "total taxes": required(MONEY),
    "total payments": required(MONEY),
    "balance": required(MONEY),
    "average room rate": required(MONEY),
}
# A row starts with market segment code, local market segment code, confirmation number.
RESERVATION_ANCHOR_WIDTH = 3


def display_version(headers: list[str]) -> int:
    if len(headers) == V2_COLUMN_COUNT:
        return 2
    if len(headers) == V1_COLUMN_COUNT:
        return 1
    raise ValueError(
        f"Expected {V1_COLUMN_COUNT} or {V2_COLUMN_COUNT} columns, got {len(headers)}"
    )


def validate_display_headers(headers: list[str]) -> int:
    version = display_version(headers)
    expected = V2_DISPLAY_HEADERS if version == 2 else V1_DISPLAY_HEADERS
    for index, header in enumerate(headers):
        if header.strip().lower() != expected[index].lower():
            raise ValueError(
                f'Header mismatch at column {index + 1}: expected "{expected[index]}", got "{header}"'
            )
    return version


def normalize_to_v2(fields: list[str]) -> list[str]:
    if len(fields) == V2_COLUMN_COUNT or len(fields) != V1_COLUMN_COUNT:
        return fields
    return [*fields[:11], "", "", *fields[11:30], "", *fields[30:]]


RESERVATION_LAYOUTS = {
    1: Layout(V1_DISPLAY_HEADERS, RESERVATION_TYPES, RESERVATION_ANCHOR_WIDTH),
    2: Layout(V2_DISPLAY_HEADERS, RESERVATION_TYPES, RESERVATION_ANCHOR_WIDTH),
}
