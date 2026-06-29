import streamlit as st
import pandas as pd
import subprocess
import os
import sys  # <-- Added to get the exact python path
import tempfile
import base64

# --- UI Configuration ---
st.set_page_config(page_title="AdServer Verification", layout="centered")

st.title("📊 AdServer Release Verification")
st.markdown("Upload your Athena/Presto CSV to generate the verification PDF report.")

# --- Step 1: File Upload ---
uploaded_file = st.file_uploader("Upload CSV Data File", type=["csv"])

if uploaded_file is not None:
    # --- Step 2: Read Dates from CSV ---
    try:
        df = pd.read_csv(uploaded_file, encoding='utf-16', sep='\t', usecols=["Date Hour"])
        df = df.rename(columns={"Date Hour": "date_hour"})
        df["date_hour"] = pd.to_datetime(df["date_hour"].astype(str).str.strip())
        available_dates = sorted(df["date_hour"].dt.strftime("%Y-%m-%d").unique())
    except Exception as e:
        st.error(f"Error reading dates from CSV: {e}")
        st.stop()

    if not available_dates:
        st.error("No valid dates found in the file.")
        st.stop()

    st.success(f"File uploaded successfully! Found {len(available_dates)} available dates.")
    st.divider()

    # --- Step 3: Configuration Form ---
    st.subheader("Configuration Settings")
    
    col1, col2 = st.columns(2)
    with col1:
        release_date = st.selectbox("Deployment Date", options=available_dates, index=len(available_dates)-1)
        hour = st.number_input("Deployment Hour (0-23 ET)", min_value=0, max_value=23, value=6)
        region = st.radio("AWS Region", options=["BOTH", "EAST", "WEST"], index=0)
        
    with col2:
        compare_date = st.selectbox("Comparison Date", options=available_dates, index=max(0, len(available_dates)-2))
        env = st.radio("Environment", options=["Production", "Canary", "Both"], index=0)
        threshold_display = st.selectbox("Significance Threshold", options=["5%", "10% (Recommended)", "15%"], index=1)

    exclude_last = st.toggle("Exclude last (potentially incomplete) hour of data?", value=True)

    threshold_map = {"5%": 0.05, "10% (Recommended)": 0.10, "15%": 0.15}
    threshold_val = threshold_map[threshold_display]

    st.divider()

    # --- Step 4: Run Script ---
    if st.button("Generate Verification Report", type="primary", use_container_width=True):
        if release_date == compare_date:
            st.error("Deployment date and Comparison date must be different.")
        else:
            with st.spinner("Analyzing data and generating charts (this takes 30-60 seconds)..."):
                
                temp_csv_path = None
                out_pdf_path = None
                
                try:
                    # Save the uploaded file to a temporary location
                    with tempfile.NamedTemporaryFile(delete=False, suffix=".csv") as tmp_csv:
                        uploaded_file.seek(0)
                        tmp_csv.write(uploaded_file.read())
                        temp_csv_path = tmp_csv.name

                    out_pdf_path = os.path.join(tempfile.gettempdir(), f"Report_{release_date}.pdf")

                    # Use sys.executable instead of hardcoding "python"
                    command = [
                        sys.executable, "verify_analysis.py",
                        "--csv", temp_csv_path,
                        "--out", out_pdf_path,
                        "--release-date", release_date,
                        "--compare-date", compare_date,
                        "--hour", str(hour),
                        "--region", region,
                        "--env", env,
                        "--threshold", str(threshold_val)
                    ]
                    
                    if not exclude_last:
                        command.append("--no-exclude-last")

                    # Execute your original script
                    subprocess.run(command, check=True, capture_output=True, text=True)
                    
                    # --- Step 5: Display & Download PDF ---
                    if os.path.exists(out_pdf_path):
                        st.success("Report generated successfully!")
                        
                        with open(out_pdf_path, "rb") as pdf_file:
                            pdf_bytes = pdf_file.read()
                            st.download_button(
                                label="Download PDF Report",
                                data=pdf_bytes,
                                file_name=f"Release_Verification_{release_date}.pdf",
                                mime="application/pdf",
                                type="primary"
                            )
                        
                        st.subheader("Report Preview")
                        base64_pdf = base64.b64encode(pdf_bytes).decode('utf-8')
                        pdf_display = f'<embed src="data:application/pdf;base64,{base64_pdf}" width="100%" height="1000" type="application/pdf">'
                        st.markdown(pdf_display, unsafe_allow_html=True)
                        
                    else:
                        st.error("Report failed to generate. Check your script logic.")
                        
                except subprocess.CalledProcessError as e:
                    st.error(f"Script execution failed:\n\n{e.stderr}")
                    
                finally:
                    # --- CRITICAL: Cleanup Temp Files ---
                    if temp_csv_path and os.path.exists(temp_csv_path):
                        os.unlink(temp_csv_path)
                    if out_pdf_path and os.path.exists(out_pdf_path):
                        os.unlink(out_pdf_path)
