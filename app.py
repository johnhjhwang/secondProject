import os
import tempfile
from pathlib import Path
from dotenv import load_dotenv
import streamlit as st
from agent import analyze_architecture, analyze_and_improve, generate_diagram, run_agent
from skills.fetch_context import fetch_and_store, delete_context, list_context

load_dotenv()

# --- UI ---
st.set_page_config(page_title="Azure Architecture Analyzer", page_icon="☁️", layout="wide")
st.title("☁️ Azure Architecture Analyzer")
st.caption("Powered by the azure-diagrams skill — analyze existing diagrams or generate new ones.")

tab1, tab2, tab3, tab4 = st.tabs(["Analyze Diagram", "Generate Diagram", "Ask Architect", "Context Links"])

# ── Tab 1: Analyze uploaded screenshot ──────────────────────────────────────
with tab1:
    col1, col2 = st.columns([1, 1], gap="large")

    with col1:
        uploaded_file = st.file_uploader(
            "Upload Architecture Diagram",
            type=["png", "jpg", "jpeg", "webp"],
            help="Supports PNG, JPG, JPEG, WEBP",
        )

        question = st.text_area(
            "Question (optional)",
            placeholder="e.g. Is this architecture production-ready? Focus on security gaps.",
            value=(
                "Analyze this Azure architecture diagram. Identify all services and their relationships, "
                "then score the overall architecture across the Azure Well-Architected Framework pillars. "
                "Provide a total score out of 100 with a breakdown per pillar, key strengths, risks, "
                "and prioritized recommendations."
            ),
            height=120,
        )

        improve = st.toggle("Generate improved diagram", value=True)
        analyze_btn = st.button("Analyze Architecture", type="primary", disabled=uploaded_file is None)

        if uploaded_file:
            st.image(uploaded_file, caption="Uploaded Diagram", use_container_width=True)

    with col2:
        if analyze_btn and uploaded_file:
            ext = uploaded_file.name.rsplit(".", 1)[-1].lower()

            with tempfile.NamedTemporaryFile(suffix=f".{ext}", delete=False) as tmp:
                tmp.write(uploaded_file.getvalue())
                tmp_path = tmp.name

            try:
                if improve:
                    with st.spinner("Analyzing and generating improved diagram..."):
                        result, improved_path = analyze_and_improve(tmp_path)
                else:
                    with st.spinner("Analyzing architecture..."):
                        result = analyze_architecture(tmp_path, question)
                    improved_path = None
            finally:
                os.unlink(tmp_path)

            st.subheader("Analysis Report")
            st.markdown(result)

            if improved_path and improved_path.exists():
                st.divider()
                st.subheader("Improved Architecture Diagram")
                st.caption("Generated with official Azure icons based on the recommendations above.")
                st.image(str(improved_path), use_container_width=True)
                with open(improved_path, "rb") as f:
                    st.download_button(
                        "Download Improved Diagram",
                        f,
                        file_name="improved_architecture.png",
                        mime="image/png",
                    )

        elif not uploaded_file:
            st.info("Upload a diagram on the left to get started.")

# ── Tab 2: Generate diagram from description ─────────────────────────────────
with tab2:
    st.subheader("Generate Azure Architecture Diagram")
    st.caption("Describe your architecture and the agent will generate a professional diagram using 700+ official Azure icons.")

    description = st.text_area(
        "Architecture Description",
        placeholder="e.g. A microservices application with AKS, API Management, Cosmos DB, Service Bus, and Azure Front Door",
        height=120,
    )
    output_name = st.text_input("Output filename (no extension)", value="architecture")

    generate_btn = st.button("Generate Diagram", type="primary", disabled=not description.strip())

    if generate_btn and description.strip():
        with st.spinner("Generating diagram..."):
            try:
                output_path = generate_diagram(description, output_name)
                st.success(f"Diagram saved to: `{output_path}`")
                st.image(str(output_path), caption="Generated Azure Architecture Diagram", use_container_width=True)
                with open(output_path, "rb") as f:
                    st.download_button("Download Diagram", f, file_name=f"{output_name}.png", mime="image/png")
            except Exception as e:
                st.error(f"Generation failed: {e}")

# ── Tab 3: Ask the architect ──────────────────────────────────────────────────
with tab3:
    st.subheader("Ask the Azure Architect")
    user_question = st.text_area(
        "Your Question",
        placeholder="e.g. What's the best way to handle secrets in AKS?",
        height=100,
    )
    ask_btn = st.button("Ask", type="primary", disabled=not user_question.strip())

    if ask_btn and user_question.strip():
        with st.spinner("Thinking..."):
            answer = run_agent(user_question)
        st.markdown(answer)

# ── Tab 4: Context Links ──────────────────────────────────────────────────────
with tab4:
    st.subheader("Context Links")
    st.caption(
        "Add webpage URLs (company standards, compliance policies, Azure guidelines) to guide "
        "diagram generation. The agent will fetch and use their content in every diagram it creates."
    )

    with st.form("add_link_form", clear_on_submit=True):
        url_input = st.text_input("Webpage URL", placeholder="https://your-firm.com/azure-standards")
        label_input = st.text_input("Label (optional)", placeholder="e.g. Firm Azure Compliance Policy")
        submitted = st.form_submit_button("Fetch & Add", type="primary")

    if submitted and url_input.strip():
        with st.spinner(f"Fetching {url_input}..."):
            try:
                entry = fetch_and_store(url_input.strip(), label_input.strip())
                st.success(f"Added: **{entry['label']}** ({entry['chars']:,} characters fetched)")
                st.rerun()
            except Exception as e:
                st.error(f"Failed to fetch URL: {e}")

    st.divider()
    st.subheader("Stored Context")

    entries = list_context()
    if not entries:
        st.info("No context links added yet. Add URLs above to guide the agent.")
    else:
        for entry in entries:
            with st.expander(f"**{entry['label']}**"):
                st.markdown(f"**URL:** {entry['url']}")
                st.markdown(f"**Fetched:** {entry['fetched_at'][:19].replace('T', ' ')}")
                st.markdown(f"**Content size:** {entry['chars']:,} characters")
                if st.button("Remove", key=f"del_{entry['url']}"):
                    delete_context(entry["url"])
                    st.rerun()
