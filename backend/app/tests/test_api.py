def test_health(client):
    r = client.get("/api/health")
    assert r.status_code == 200
    assert r.json()["status"] == "ok"

def test_ingest_and_ask(client):
    r = client.post("/api/ingest")
    assert r.status_code == 200
    # Ask a deterministic question
    r2 = client.post("/api/ask", json={"query":"What is the refund window for small appliances?"})
    assert r2.status_code == 200
    data = r2.json()
    assert "citations" in data and len(data["citations"]) > 0
    assert "answer" in data and isinstance(data["answer"], str)


def test_acceptance_question_returns_damaged_blender_sources(client):
    client.post("/api/ingest")

    response = client.post(
        "/api/ask",
        json={"query": "Can a customer return a damaged blender after 20 days?", "k": 4},
    )

    assert response.status_code == 200
    payload = response.json()
    cited_titles = {citation["title"] for citation in payload["citations"]}

    assert "Returns_and_Refunds.md" in cited_titles
    assert "Warranty_Policy.md" in cited_titles


def test_acceptance_question_shipping_sla_sources(client):
    client.post("/api/ingest")

    response = client.post(
        "/api/ask",
        json={"query": "What’s the shipping SLA to East Malaysia for bulky items?", "k": 4},
    )

    assert response.status_code == 200
    payload = response.json()
    cited_titles = {citation["title"] for citation in payload["citations"]}
    chunks_text = " ".join(chunk["text"] for chunk in payload["chunks"])

    assert "Delivery_and_Shipping.md" in cited_titles
    assert "bulky" in chunks_text.lower()
    assert "east malaysia" in chunks_text.lower()


def test_masks_sensitive_output(monkeypatch, client):
    from app.main import engine

    monkeypatch.setattr(
        engine,
        "retrieve",
        lambda query, k=4: [
            {
                "title": "Compliance_Notes.md",
                "section": "Compliance Notes (PDPA)",
                "text": "Customer email is jane@example.com and address is 12 Jalan Ampang.",
            }
        ],
    )
    monkeypatch.setattr(
        engine.llm,
        "generate",
        lambda query, contexts: "Contact jane@example.com or 60123456789 at 12 Jalan Ampang.",
    )

    response = client.post("/api/ask", json={"query": "Show customer details"})

    assert response.status_code == 200
    payload = response.json()
    assert "[redacted-email]" in payload["answer"]
    assert "[redacted-phone]" in payload["answer"]
    assert "[redacted-address]" in payload["answer"]
    assert "[redacted-email]" in payload["chunks"][0]["text"]
    assert "[redacted-address]" in payload["chunks"][0]["text"]
