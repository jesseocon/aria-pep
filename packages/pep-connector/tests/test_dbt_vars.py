from pep_connector.transform import dbt_vars


def test_dbt_vars_are_plain_strings() -> None:
    rendered = dbt_vars(
        {
            "org_id": "1791938321619893710",
            "development_property_id": "cmv7ecqb2001mbquy7e8snfww",
            "production_property_id": "prod-id",
        },
        "development",
        "dallas-love-field-pep-production",
    )
    assert rendered == {
        "bq_project": "hospitalityops-dev",
        "org_id": "1791938321619893710",
        "source": "pep",
        "property_id": "cmv7ecqb2001mbquy7e8snfww",
        "property_slug": "dallas-love-field-pep-production",
    }
    assert "{{" not in "".join(rendered.values())
