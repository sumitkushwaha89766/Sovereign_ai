from docx import Document

from app.agent.tools.docgen_tool import ApprovalNoteInput, generate_approval_note_docx


def test_final_docx_contains_approval_decision(tmp_path, monkeypatch):
    monkeypatch.setattr(
        "app.agent.tools.docgen_tool._DELIVERABLES_ROOT",
        tmp_path / "deliverables",
    )
    path = generate_approval_note_docx(
        ApprovalNoteInput(
            subject="Continued Operation - P-204",
            equipment_id="P-204",
            inspection_report_id="IR-892",
            inspection_date="2026-08-15",
            inspector_name="R. K. Sharma",
            requester_name="engineer1",
            background="Inspection completed.",
            risk_assessment="Controlled.",
            conditions=["Monitor every 4 hours."],
            recommendation="Continue under conditions.",
            run_id=99,
            approval_status="approved",
            approver_name="admin1",
            approval_date="2026-09-09",
            approval_comment="Reviewed and accepted.",
        )
    )

    text = "\n".join(paragraph.text for paragraph in Document(path).paragraphs)
    assert "APPROVED for continued operation" in text
    assert "Raised by:  engineer1" in text
    assert "Reviewed by:  admin1" in text
    assert "admin1" in text
    assert "Reviewed and accepted." in text
