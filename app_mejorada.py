import streamlit as st
import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
from datetime import datetime, time
import requests
from io import StringIO
import re
import warnings
from fpdf import FPDF

warnings.filterwarnings('ignore')

# --- CONFIGURACIÓN DE LA PÁGINA ---
st.set_page_config(
    page_title="Sistema de Análisis Presión Mancomunidad La Esperanza",
    page_icon="💧",
    layout="wide",
    initial_sidebar_state="expanded"
)

# --- ESTILOS CSS PARA UN DISEÑO PROFESIONAL ---
st.markdown("""
<style>
    :root {
        --primary-color: #005f73; --secondary-color: #0a9396; --background-color: #f0f2f6;
        --card-background-color: #ffffff; --text-color: #262730; --success-color: #2a9d8f;
        --warning-color: #e9c46a; --danger-color: #e76f51; --high-pressure-color: #9b2226;
    }
    .main { background-color: var(--background-color); }
    .main-header {
        background: linear-gradient(90deg, var(--primary-color) 0%, var(--secondary-color) 100%);
        padding: 1.5rem; border-radius: 10px; color: white; text-align: center;
        margin-bottom: 2rem; box-shadow: 0 4px 15px rgba(0, 95, 115, 0.2);
    }
    .main-header h1 { font-size: 2.5rem; font-weight: bold; }
    .main-header h3 { font-size: 1.2rem; opacity: 0.9; }
    .stMetric {
        background-color: var(--card-background-color); border-radius: 8px; padding: 1rem;
        border-left: 5px solid var(--primary-color); box-shadow: 0 2px 4px rgba(0,0,0,0.05);
    }
    [data-testid="stMetricValue"], [data-testid="stMetricLabel"], [data-testid="stMetricDelta"] {
        color: var(--text-color) !important;
    }
    .alert {
        padding: 1rem; margin: 1rem 0; border-radius: 8px; font-weight: bold;
        border-left-width: 5px; border-left-style: solid; box-shadow: 0 2px 4px rgba(0,0,0,0.05);
    }
    .alert-critical { background-color: #fee2e2; border-left-color: var(--danger-color); color: #92400e; }
    .alert-high-pressure { background-color: #f5d0d0; border-left-color: var(--high-pressure-color); color: #9b2226; }
    .alert-warning { background-color: #fffbeb; border-left-color: var(--warning-color); color: #92400e; }
    .alert-success { background-color: #f0fdf4; border-left-color: var(--success-color); color: #166534; }
    .technical-section {
        background-color: var(--card-background-color); padding: 1.5rem; border-radius: 8px;
        margin-top: 1rem; border: 1px solid #e0e0e0;
    }
</style>
""", unsafe_allow_html=True)

# --- CLASE PARA GENERACIÓN DE PDF ---
class PDF(FPDF):
    def header(self):
        self.set_font('Arial', 'B', 12)
        self.cell(0, 10, 'Reporte Técnico de Análisis de Presión', 0, 1, 'C')
        self.set_font('Arial', '', 8)
        self.cell(0, 5, f"Fecha de Generación: {datetime.now().strftime('%d/%m/%Y %H:%M:%S')}", 0, 1, 'C')
        self.ln(5)

    def footer(self):
        self.set_y(-15)
        self.set_font('Arial', 'I', 8)
        self.cell(0, 10, 'Autor del Reporte: Ing. Leither Torres', 0, 0, 'L')
        self.cell(0, 10, f'Página {self.page_no()}/{{nb}}', 0, 0, 'R')

    def chapter_title(self, title):
        self.set_font('Arial', 'B', 12)
        self.set_fill_color(224, 235, 255)
        self.cell(0, 8, title, 0, 1, 'L', 1)
        self.ln(4)

    def chapter_body(self, body):
        safe_body = body.encode('latin-1', 'replace').decode('latin-1')
        self.set_font('Arial', '', 10)
        self.multi_cell(0, 5, safe_body)
        self.ln()

    def add_table(self, title, data, column_widths):
        self.chapter_title(title)
        self.set_font('Arial', 'B', 7)
        for i, header in enumerate(data.columns):
            self.cell(column_widths[i], 7, str(header), 1, 0, 'C')
        self.ln()
        self.set_font('Arial', '', 6)
        for _, row in data.iterrows():
            for i, item in enumerate(row):
                self.cell(column_widths[i], 6, str(item), 1)
            self.ln()
        self.ln(5)

# --- CONFIGURACIÓN DE LA API ---
# Nota: La API Key se gestiona a través de los "Secrets" de Streamlit para mayor seguridad.
# En local, crea un archivo .streamlit/secrets.toml y añade tu clave.
OPENROUTER_API_KEY = st.secrets.get("OPENROUTER_API_KEY", "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")
API_URL = "https://openrouter.ai/api/v1/chat/completions"

# --- CLASE PRINCIPAL DE ANÁLISIS ---
class WaterSystemPressureAnalyzer:
    def __init__(self):
        self.data = None
        self.thresholds = {}

    def set_thresholds(self, thresholds):
        self.thresholds = thresholds

    def detect_file_format(self, content):
        lines = content.strip().split('\n')
        if not lines: return None, None, None
        first_line = lines[0]
        separator = '\t'
        if '\t' in first_line and len(first_line.split('\t')) > 1: separator = '\t'
        elif ';' in first_line and len(first_line.split(';')) > 1: separator = ';'
        elif ',' in first_line and len(first_line.split(',')) > 1: separator = ','
        try:
            first_column = first_line.split(separator)[0].strip()
            has_header = not bool(re.match(r'^\d', first_column))
        except IndexError: has_header = False
        return separator, has_header, lines

    def parse_datetime(self, date_str):
        formats = ["%d/%m/%Y %H:%M", "%d/%m/%Y %H:%M:%S", "%Y-%m-%d %H:%M", "%Y-%m-%d %H:%M:%S", "%d-%m-%Y %H:%M", "%d-%m-%Y %H:%M:%S"]
        for fmt in formats:
            try: return pd.to_datetime(date_str, format=fmt)
            except (ValueError, TypeError): continue
        try: return pd.to_datetime(date_str, dayfirst=True)
        except (ValueError, TypeError): return None

    def load_data(self, uploaded_file):
        try:
            content = uploaded_file.read().decode('utf-8', errors='ignore')
            separator, has_header, _ = self.detect_file_format(content)
            df = pd.read_csv(StringIO(content), sep=separator, header=0 if has_header else None, engine='python', skipinitialspace=True)

            if df.shape[1] < 2:
                st.error(f"❌ El archivo no tiene al menos 2 columnas. Verifique el separador."); return False

            df = df.iloc[:, :2]
            df.columns = ['timestamp_str', 'pressure']
            
            df.dropna(how='all', inplace=True)
            if df.empty: st.error("❌ El archivo no contiene filas con datos."); return False
            
            df['pressure'] = df['pressure'].astype(str).str.replace(',', '.', regex=False)
            df['pressure'] = pd.to_numeric(df['pressure'], errors='coerce')
            df.dropna(subset=['pressure'], inplace=True)
            if df.empty: st.error("❌ No se encontraron valores de presión numéricos válidos."); return False
                
            df['timestamp'] = df['timestamp_str'].astype(str).apply(self.parse_datetime)
            if df['timestamp'].isnull().all(): st.error("❌ No se pudo interpretar ninguna fecha."); return False
            df.dropna(subset=['timestamp'], inplace=True)
            if df.empty: st.error("❌ No quedaron datos válidos tras procesar."); return False
            
            self.data = df[['timestamp', 'pressure']].sort_values('timestamp').reset_index(drop=True)
            return True
        except Exception as e:
            st.error(f"❌ Error al procesar el archivo: {e}"); return False

    def get_status(self, max_p):
        if max_p >= self.thresholds['excelente']: return "Excelente"
        if max_p >= self.thresholds['muy_bueno']: return "Muy Bueno"
        if max_p >= self.thresholds['bueno']: return "Bueno"
        if max_p >= self.thresholds['regular']: return "Regular"
        if max_p >= self.thresholds['malo']: return "Malo"
        if max_p >= self.thresholds['muy_malo']: return "Muy Malo (Rotura Probable)"
        return "Suspensión de Servicio"

    def analyze_daily_performance(self, data):
        if data is None or data.empty: return pd.DataFrame()
        data['date'] = data['timestamp'].dt.date
        daily_summary = []
        for date, group in data.groupby('date'):
            max_p = group['pressure'].max()
            status = self.get_status(max_p)
            
            pressure_started = group[group['pressure'] >= 3]
            arrival_time = pressure_started['timestamp'].min() if not pressure_started.empty else None
            
            pressure_ended_mask = (group['timestamp'].dt.time > time(12, 0)) & (group['pressure'] < 1)
            pressure_ended = group[pressure_ended_mask]
            cut_time = pressure_ended['timestamp'].min() if not pressure_ended.empty else None

            duration_hours = ((cut_time - arrival_time).total_seconds() / 3600) if pd.notnull(arrival_time) and pd.notnull(cut_time) else 0
            
            day_name_es = {'Monday': 'Lunes', 'Tuesday': 'Martes', 'Wednesday': 'Miércoles', 'Thursday': 'Jueves', 'Friday': 'Viernes', 'Saturday': 'Sábado', 'Sunday': 'Domingo'}
            day_of_week = day_name_es[date.strftime('%A')]

            daily_summary.append({
                "Fecha": date.strftime('%d/%m/%Y'), "Día": day_of_week, "Estado": status,
                "Presión Máx (PSI)": f"{max_p:.2f}",
                "Hora Llegada": arrival_time.strftime('%H:%M') if pd.notnull(arrival_time) else "N/A",
                "Hora Corte": cut_time.strftime('%H:%M') if pd.notnull(cut_time) else "N/A",
                "Duración (H)": f"{duration_hours:.2f}"
            })
        return pd.DataFrame(daily_summary)

# --- FUNCIONES DE VISUALIZACIÓN ---
def create_time_series_chart(data, thresholds):
    fig = go.Figure()
    fig.add_trace(go.Scatter(x=data['timestamp'], y=data['pressure'], mode='lines', name='Presión', line=dict(color='#005f73', width=1.5)))
    fig.add_hline(y=thresholds['excelente'], line_dash="dash", line_color="#2a9d8f", annotation_text=f"Excelente ≥ {thresholds['excelente']} PSI")
    fig.add_hline(y=thresholds['sobrepresion'], line_dash="dot", line_color="#9b2226", annotation_text=f"Sobrepresión > {thresholds['sobrepresion']} PSI")
    
    if not data.empty:
        fig.add_hrect(y0=0, y1=thresholds['muy_malo'], fillcolor="#e76f51", opacity=0.1, layer="below", line_width=0, annotation_text="Suspensión")
        
    fig.update_layout(title='<b>Análisis Temporal de Presión del Sistema</b>', xaxis_title='Fecha y Hora', yaxis_title='Presión (PSI)', height=500, legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="right", x=1))
    return fig

def create_duration_chart(daily_summary):
    if daily_summary.empty: return go.Figure()
    summary = daily_summary.copy()
    summary['Duración (H)'] = pd.to_numeric(summary['Duración (H)'])
    
    color_map = {
        "Excelente": "#2a9d8f", "Muy Bueno": "#5fba7d", "Bueno": "#8acb88",
        "Regular": "#e9c46a", "Malo": "#f4a261", "Muy Malo (Rotura Probable)": "#e76f51",
        "Suspensión de Servicio": "#d00000"
    }
    
    fig = px.bar(summary, x='Fecha', y='Duración (H)', title='<b>Duración Diaria del Servicio con Presión Adecuada</b>',
                 labels={'Fecha': 'Día', 'Duración (H)': 'Horas de Servicio'},
                 color='Estado', color_discrete_map=color_map)
    fig.update_layout(xaxis={'type': 'category'})
    return fig

# --- FUNCIONES DE REPORTE ---
def generate_ai_report(daily_summary, system_prompt):
    try:
        user_content = f"Por favor, genera un reporte técnico en español basado en el siguiente resumen de rendimiento diario:\n\nTABLA DE RENDIMIENTO DIARIO:\n{daily_summary.to_string()}\n\nAnaliza esta tabla siguiendo las instrucciones del sistema."
        response = requests.post(API_URL, headers={"Authorization": f"Bearer {OPENROUTER_API_KEY}"}, json={"model": "mistralai/mistral-7b-instruct:free", "messages": [{"role": "system", "content": system_prompt}, {"role": "user", "content": user_content}]})
        return response.json()['choices'][0]['message']['content'] if response.status_code == 200 else f"Error en la API: {response.status_code} - {response.text}"
    except Exception as e:
        return f"Error generando reporte: {e}"

def generate_pdf_report(daily_summary, ai_report):
    pdf = PDF('P', 'mm', 'A4')
    pdf.alias_nb_pages()
    pdf.add_page()
    pdf.set_font('Arial', 'B', 18)
    pdf.cell(0, 15, 'Reporte Técnico de Análisis de Presión', 0, 1, 'C'); pdf.ln(5)
    
    body_text = ai_report.replace('**', '').replace('##', '')
    lines = body_text.split('\n')
    for line in lines:
        line = line.strip()
        if not line: continue
        if re.match(r'^\d+\.\s+[A-Z\s]+:', line):
            pdf.chapter_title(line.replace(':', ''))
        else:
            pdf.set_font('Arial', '', 10)
            pdf.multi_cell(0, 5, line.encode('latin-1', 'replace').decode('latin-1')); pdf.ln(1)
            
    pdf.add_page(orientation='L')
    column_widths = [25, 25, 40, 30, 30, 30, 30]
    pdf.add_table("Tabla de Rendimiento Diario Detallado", daily_summary, column_widths)
    return bytes(pdf.output())

# --- APLICACIÓN PRINCIPAL ---
def main():
    st.markdown("""<div class="main-header"><h1>Sistema de Análisis Presión Mancomunidad La Esperanza</h1><h3>diagnostico del tramo 3, El Vergel - Cambio</h3></div>""", unsafe_allow_html=True)
    
    if 'analyzer' not in st.session_state:
        st.session_state.analyzer = WaterSystemPressureAnalyzer()

    with st.sidebar:
        st.header("⚙️ Panel de Control")
        thresholds = {
            "excelente": st.number_input("Excelente ≥ (PSI)", min_value=10.0, max_value=50.0, value=18.0, step=0.5),
            "muy_bueno": st.number_input("Muy Bueno ≥ (PSI)", min_value=10.0, max_value=50.0, value=17.5, step=0.5),
            "bueno": st.number_input("Bueno ≥ (PSI)", min_value=10.0, max_value=50.0, value=16.5, step=0.5),
            "regular": st.number_input("Regular ≥ (PSI)", min_value=5.0, max_value=49.0, value=15.0, step=0.5),
            "malo": st.number_input("Malo ≥ (PSI)", min_value=5.0, max_value=49.0, value=10.0, step=0.5),
            "muy_malo": st.number_input("Muy Malo ≥ (PSI)", min_value=0.0, max_value=49.0, value=5.0, step=0.5),
            "sobrepresion": st.number_input("Alerta Sobrepresión > (PSI)", min_value=20.0, max_value=60.0, value=25.0, step=1.0)
        }
        st.session_state.analyzer.set_thresholds(thresholds)
        
        st.markdown("---")
        uploaded_file = st.file_uploader("📁 Cargar Archivo de Datos (.csv, .txt)", type=['csv', 'txt'])

        if uploaded_file and st.button("🚀 Procesar Datos", type="primary", use_container_width=True):
            with st.spinner('Analizando archivo...'):
                for key in ['ai_report', 'pdf_report', 'pdf_ready', 'date_range']:
                    if key in st.session_state: del st.session_state[key]
                if st.session_state.analyzer.load_data(uploaded_file):
                    st.session_state.date_range = (st.session_state.analyzer.data['timestamp'].min().date(), st.session_state.analyzer.data['timestamp'].max().date())
                    st.success("✅ Datos procesados con éxito."); st.rerun()

    if st.session_state.analyzer.data is None:
        st.info("👈 Cargue un archivo de datos para comenzar el análisis."); return

    with st.sidebar:
        st.markdown("---"); st.header("📅 Filtro por Fecha")
        if 'date_range' in st.session_state:
            min_date, max_date = st.session_state.date_range
            selected_range = st.date_input("Seleccione el rango:", value=(min_date, max_date), min_value=min_date, max_value=max_date)
            start_date, end_date = (selected_range[0], selected_range[1]) if len(selected_range) == 2 else (min_date, max_date)
            mask = (st.session_state.analyzer.data['timestamp'].dt.date >= start_date) & (st.session_state.analyzer.data['timestamp'].dt.date <= end_date)
            filtered_data = st.session_state.analyzer.data.loc[mask]
        else: filtered_data = st.session_state.analyzer.data

    if filtered_data.empty:
        st.warning("⚠️ No hay datos para el rango de fechas seleccionado."); return

    daily_summary_df = st.session_state.analyzer.analyze_daily_performance(filtered_data)
    
    st.subheader("📊 Resumen de Rendimiento por Día")
    if not daily_summary_df.empty:
        status_counts = daily_summary_df['Estado'].value_counts()
        dias_sobrepresion = daily_summary_df[pd.to_numeric(daily_summary_df['Presión Máx (PSI)']) > thresholds['sobrepresion']].shape[0]

        cols = st.columns(3)
        cols[0].metric("✅ Días con Buen Servicio (Bueno o Superior)", status_counts.get("Excelente", 0) + status_counts.get("Muy Bueno", 0) + status_counts.get("Bueno", 0))
        cols[1].metric("❌ Días con Mal Servicio (Regular o Inferior)", status_counts.get("Regular", 0) + status_counts.get("Malo", 0) + status_counts.get("Muy Malo (Rotura Probable)", 0) + status_counts.get("Suspensión de Servicio", 0))
        cols[2].metric("🚨 Días con Sobrepresión", dias_sobrepresion)
        
        if dias_sobrepresion > 0:
            st.markdown(f"<div class='alert alert-high-pressure'><b>ALERTA DE SOBREPRESIÓN:</b> Se detectaron {dias_sobrepresion} días con presiones superiores a {thresholds['sobrepresion']} PSI. Esto puede causar daños en la red y en las instalaciones de los usuarios.</div>", unsafe_allow_html=True)

    st.markdown("---")
    tab_dashboard, tab_report = st.tabs(["📈 Dashboard Interactivo", "📋 Generador de Reportes"])
    
    with tab_dashboard:
        fig_time = create_time_series_chart(filtered_data, thresholds)
        st.plotly_chart(fig_time, use_container_width=True)
        
        fig_duration = create_duration_chart(daily_summary_df)
        st.plotly_chart(fig_duration, use_container_width=True)

        st.dataframe(daily_summary_df, use_container_width=True)

    with tab_report:
        st.subheader("🤖 Instrucción para la IA (System Prompt)")
        default_system_prompt = """Eres un Ingeniero Civil experto en Hidráulica y Sistemas de Agua Potable, con más de 20 años de experiencia en análisis y diagnóstico de redes para la Mancomunidad La Esperanza. Tu tarea es generar un reporte técnico en español, con un tono formal, claro y concluyente, similar a un memorando oficial.

Considera el siguiente contexto operativo: el servicio de agua con presión inicia aproximadamente a las 05:30 y finaliza cerca de las 18:00. Fuera de este horario, las presiones nulas o negativas no necesariamente indican una falla.

El reporte debe estar estructurado en las siguientes secciones:
1.  **ASUNTO:** Análisis de Comportamiento de Presiones en el Tramo 3: El Vergel - Cambio.
2.  **RESUMEN EJECUTIVO:** Síntesis de los hallazgos más importantes, el estado general del sistema y las conclusiones principales.
3.  **ANÁLISIS DE COMPORTAMIENTO DIARIO:** Evalúa el rendimiento general basándote en la clasificación de los días (Excelente, Bueno, Malo, etc.). Identifica patrones, como la recurrencia de días deficientes en ciertas fechas o días de la semana.
4.  **ANÁLISIS DE HORARIOS DE SERVICIO:** Comenta sobre la consistencia de la 'Hora de Llegada' y la 'Duración del Servicio'. Compara los horarios reales con el horario operativo esperado (05:30 - 18:00). ¿Son estables los horarios o hay variabilidad? ¿Cómo afecta esto al abastecimiento?
5.  **DIAGNÓSTICO DE DÍAS CRÍTICOS Y ANOMALÍAS:** Enfócate en los días clasificados como 'Malo', 'Muy Malo' o 'Suspensión'. Analiza sus presiones máximas y duraciones de servicio para determinar la severidad del problema. Menciona cualquier día con sobrepresión.
6.  **CONCLUSIONES Y RECOMENDACIONES:** Finaliza con conclusiones claras y un plan de acción con recomendaciones priorizadas (Alta, Media, Baja) para corregir las deficiencias encontradas."""
        
        custom_prompt = st.text_area("Edite las instrucciones para la IA si es necesario:", value=default_system_prompt, height=300)

        if st.button("Generar Diagnóstico con IA", use_container_width=True) and not daily_summary_df.empty:
            with st.spinner("La IA está analizando los datos y redactando el informe..."):
                st.session_state.ai_report = generate_ai_report(daily_summary_df, custom_prompt)
        
        if 'ai_report' in st.session_state and st.session_state.ai_report:
            st.markdown("<div class='technical-section'>", unsafe_allow_html=True); st.markdown(st.session_state.ai_report); st.markdown("</div>", unsafe_allow_html=True)
            st.markdown("---"); st.subheader("📄 Exportar Reporte Profesional en PDF")

            if st.button("📥 Crear PDF para Descargar", type="primary", use_container_width=True):
                with st.spinner("Creando PDF..."):
                    pdf_bytes = generate_pdf_report(daily_summary_df, st.session_state.ai_report)
                    st.session_state.pdf_report = pdf_bytes
                    st.session_state.pdf_ready = True
            
            if 'pdf_ready' in st.session_state and st.session_state.pdf_ready:
                st.download_button(label="✅ PDF Listo. ¡Descargar Aquí!", data=st.session_state.pdf_report, file_name=f"Reporte_Tecnico_Presion_{datetime.now().strftime('%Y%m%d')}.pdf", mime="application/pdf", use_container_width=True)

if __name__ == "__main__":
    main()


