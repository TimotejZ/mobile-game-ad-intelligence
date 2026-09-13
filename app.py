import streamlit as st
import json
import os
from ad_generator import (
    get_gemini_client_and_model,
    build_prompt,
    call_gemini_api,
    generate_mock_concepts,
    generate_mock_variants,
    score_and_rank_concepts,
    build_report,
)

st.set_page_config(page_title="Mobile Game Ad Intelligence", page_icon="🎮", layout="wide")

st.title("🎮 Mobile Game Ad Intelligence Generator")
st.write("Generate data-driven video ad concepts & copy variants powered by AI & Engagement Scoring.")

with st.sidebar:
    st.header("⚙️ Configuration")
    api_key_input = st.text_input("Gemini API Key (Optional)", type="password", help="Leave blank to run in Mock Mode.")
    if api_key_input:
        os.environ["GEMINI_API_KEY"] = api_key_input

st.subheader("1. Enter Game Details")
col1, col2, col3 = st.columns(3)

with col1:
    game_name = st.text_input("Game Name", value="Block Puzzle Pro")
with col2:
    genre = st.text_input("Genre", value="Puzzle")
with col3:
    audience = st.text_input("Target Audience", value="Casual commuters aged 25-40")

if st.button("🚀 Generate Ad Campaign", type="primary"):
    with st.spinner("Analyzing audience and generating concepts..."):
        client, model_name = get_gemini_client_and_model()
        
        result_payload = None
        if client is not None:
            prompt = build_prompt(game_name, genre, audience)
            result_payload = call_gemini_api(client, model_name, prompt)

        if result_payload is not None:
            source = "gemini-api"
            raw_concepts = result_payload["concepts"][:3]
            raw_variants = result_payload["ad_variants"][:5]
        else:
            source = "mock-fallback"
            raw_concepts = generate_mock_concepts(game_name, genre, audience)
            raw_variants = generate_mock_variants(game_name, genre, audience)

        concepts = score_and_rank_concepts(raw_concepts)
        variants = [{"headline": v.get("headline", ""), "body": v.get("body", ""), "cta": v.get("cta", "")} for v in raw_variants]
        
        report = build_report(game_name, genre, audience, source, model_name, concepts, variants)

        st.success(f"Generated successfully! (Data Source: {source})")
        
        # Display Concepts
        st.subheader("🎯 Ranked Video Ad Scripts")
        for concept in concepts:
            with st.expander(f"Rank #{concept['rank']} | Score: {concept['engagement_score']}/100 — Hook: {concept['hook']}", expanded=True):
                st.write(f"**Core Gameplay Concept:** {concept['gameplay_concept']}")
                st.write(f"**Call To Action:** {concept['call_to_action']}")
                if concept.get("platform_notes"):
                    st.info(f"**Platform Notes:** {concept['platform_notes']}")
                
                bd = concept['score_breakdown']
                st.caption(f"Score breakdown — Hook length: {bd['hook_length_score']} | Verbs score: {bd['action_verb_score']} | Clarity: {bd['clarity_score']}")

        # Display Copy Variants
        st.subheader("📝 Short-Form Ad Copy Variants")
        v_cols = st.columns(len(variants))
        for idx, (col, var) in enumerate(zip(v_cols, variants), 1):
            with col:
                st.markdown(f"**Variant {idx}**")
                st.write(f"*{var['headline']}*")
                st.write(var['body'])
                st.caption(f"CTA: {var['cta']}")

        # Export Buttons
        st.subheader("📥 Export Results")
        json_data = json.dumps(report, indent=2)
        st.download_button("Download JSON Report", data=json_data, file_name="campaign_report.json", mime="application/json")
