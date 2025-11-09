import pandas as pd
import dash
from dash import dcc
from dash import html
import plotly.express as px

# --- 1. डेटा लोडिंग और तैयारी ---

FILE_PATH = "Automation Done sheet.xlsx - VLOOKUP_Output.csv" 
DRIVER_TIME_COL = 'driver_start_time' # H-कॉलम
VEHICLE_COL = 'vehicle_no'
CIRCLE_COL = 'circle' 
DATE_COL = 'date'

# उपस्थिति श्रेणियों का मानचित्रण
ABSENT_STATUSES = ['OD_Approved', 'Absent', 'WO_Approved', 'PL_Approved']
PRESENT_STATUSES = ['Present', 'Present_Approved', 'NJ']

try:
    df = pd.read_csv(FILE_PATH)
    df[DATE_COL] = pd.to_datetime(df[DATE_COL], errors='coerce').dt.date
    attendance_cols = [col for col in df.columns if 'Sep' in col and '12:00AM' in col]
    
except Exception as e:
    print(f"❌ डेटा लोडिंग में त्रुटि: {e}")
    df = pd.DataFrame()
    attendance_cols = []


# --- 2. अटेंडेंस प्रोसेसिंग फंक्शन (Total P & A Days शामिल) ---

def process_combined_attendance(data_frame, att_cols):
    if data_frame.empty or not att_cols:
        return pd.DataFrame(), pd.DataFrame()
        
    # --- A. ड्राइवर अटेंडेंस को दैनिक रूप से तैयार करना (P/A) ---
    driver_df = data_frame[[DATE_COL, CIRCLE_COL, VEHICLE_COL, DRIVER_TIME_COL]].copy()
    driver_df['Driver_Date'] = pd.to_datetime(driver_df[DRIVER_TIME_COL], errors='coerce').dt.date
    driver_df['Driver_Status'] = driver_df.apply(
        lambda row: 'P' if pd.notna(row['Driver_Date']) and row['Driver_Date'] == row[DATE_COL] else 'A', axis=1
    )
    driver_pivot = driver_df.groupby([CIRCLE_COL, VEHICLE_COL, DATE_COL])['Driver_Status'].first().unstack(fill_value='A')
    
    
    # --- B. इंजीनियर अटेंडेंस को दैनिक रूप से तैयार करना (P/A) ---
    melted_df = data_frame.melt(
        id_vars=[CIRCLE_COL, VEHICLE_COL], 
        value_vars=att_cols, 
        var_name='Attendance_Date', 
        value_name='Status'
    )
    
    def map_engineer_status(status):
        if pd.isna(status): return 'A'
        status_str = str(status).strip()
        if status_str in PRESENT_STATUSES: return 'P'
        elif status_str in ABSENT_STATUSES: return 'A'
        return 'A'
        
    melted_df['Engineer_Status'] = melted_df['Status'].apply(map_engineer_status)
    date_map = {col: pd.to_datetime(col).date() for col in att_cols}
    melted_df['Date'] = melted_df['Attendance_Date'].map(date_map)
    engineer_pivot = melted_df.groupby([CIRCLE_COL, VEHICLE_COL, 'Date'])['Engineer_Status'].first().unstack(fill_value='A')
    
    
    # --- C. ड्राइवर और इंजीनियर को मिलाएं (Final Combine Logic) ---
    common_indices = driver_pivot.index.intersection(engineer_pivot.index)
    common_dates = driver_pivot.columns.intersection(engineer_pivot.columns)
    
    driver_pivot = driver_pivot.loc[common_indices, common_dates]
    engineer_pivot = engineer_pivot.loc[common_indices, common_dates]
    
    # कंबाइंड Pivot Table (P/A with color code)
    combined_pivot = pd.DataFrame(index=driver_pivot.index, columns=driver_pivot.columns)
    
    for date in common_dates:
        for index in common_indices:
            driver_stat = driver_pivot.loc[index, date]
            engineer_stat = engineer_pivot.loc[index, date]
            
            if driver_stat == 'P' and engineer_stat == 'P':
                combined_pivot.loc[index, date] = 'P (Full Green)'
            elif driver_stat == 'P' and engineer_stat == 'A':
                combined_pivot.loc[index, date] = 'P'
            elif driver_stat == 'A' and engineer_stat == 'P':
                combined_pivot.loc[index, date] = 'A'
            elif driver_stat == 'A' and engineer_stat == 'A':
                combined_pivot.loc[index, date] = 'A'

    # --- D. Total Present & Absent Days कैलकुलेट करें ---
    
    # 1. Driver Totals
    driver_total_p = (driver_pivot == 'P').sum(axis=1).rename('Total_Driver_P')
    driver_total_a = (driver_pivot == 'A').sum(axis=1).rename('Total_Driver_A')
    
    # 2. Engineer Totals
    engineer_total_p = (engineer_pivot == 'P').sum(axis=1).rename('Total_Engineer_P')
    engineer_total_a = (engineer_pivot == 'A').sum(axis=1).rename('Total_Engineer_A')
    
    # 3. सारांश डेटाफ्रेम बनाएं
    summary_df = pd.concat([driver_total_p, driver_total_a, engineer_total_p, engineer_total_a], axis=1)

    return combined_pivot, summary_df


final_combined_pivot, summary_df = process_combined_attendance(df, attendance_cols)


# --- 3. Dash App लेआउट ---

app = dash.Dash(__name__)

COLOR_STYLE = {
    'P (Full Green)': 'background-color: #c6e4b8; color: black; font-weight: bold;', 
    'P': 'background-color: #b8c6e4; color: black;', 
    'A': 'background-color: #f7a9a9; color: black;', 
    'default': 'background-color: white; color: black;'
}

def generate_styled_table(dataframe, summary_data, style_map):
    """Pandas DataFrame को colour-coded HTML टेबल में बदलता है, सभी Totals के साथ"""
    if dataframe.empty or summary_data.empty:
        return html.Div("डेटा उपलब्ध नहीं।")

    # Column Headers (तारीख + Totals)
    header = [
        html.Th(CIRCLE_COL, style={'position': 'sticky', 'left': 0, 'background-color': '#f2f2f2', 'zIndex': 100}),
        html.Th(VEHICLE_COL, style={'position': 'sticky', 'left': 60, 'background-color': '#f2f2f2', 'zIndex': 100})
    ] + [html.Th(col) for col in dataframe.columns] + [
        html.Th("Driver P", style={'background-color': '#e0f7fa', 'font-weight': 'bold', 'color': '#007bff'}),
        html.Th("Driver A", style={'background-color': '#ffebee', 'font-weight': 'bold', 'color': '#d32f2f'}),
        html.Th("Engineer P", style={'background-color': '#e8f5e9', 'font-weight': 'bold', 'color': '#28a745'}),
        html.Th("Engineer A", style={'background-color': '#fbe9e7', 'font-weight': 'bold', 'color': '#ff7043'})
    ]
    
    # Table Body
    rows = []
    
    for index in dataframe.index[:100]: # केवल पहले 100 Rows दिखाएँ
        circle, vehicle = index
        
        row_cells = [
            html.Td(circle, style={'position': 'sticky', 'left': 0, 'background-color': '#f2f2f2', 'borderRight': '2px solid #ccc'}),
            html.Td(vehicle, style={'position': 'sticky', 'left': 60, 'background-color': '#f2f2f2'})
        ]
        
        # Daily Attendance Columns
        for date in dataframe.columns:
            status = dataframe.loc[index, date]
            
            if status == 'P (Full Green)': style = style_map['P (Full Green)']
            elif status == 'P': style = style_map['P']
            elif status == 'A': style = style_map['A']
            else: style = style_map['default']
                
            row_cells.append(html.Td(status.split('(')[0].strip(), style=style))
        
        # Total P & A Days Columns
        row_cells.append(html.Td(summary_data.loc[index, 'Total_Driver_P'], style={'background-color': '#e0f7fa', 'font-weight': 'bold'}))
        row_cells.append(html.Td(summary_data.loc[index, 'Total_Driver_A'], style={'background-color': '#ffebee', 'font-weight': 'bold'}))
        row_cells.append(html.Td(summary_data.loc[index, 'Total_Engineer_P'], style={'background-color': '#e8f5e9', 'font-weight': 'bold'}))
        row_cells.append(html.Td(summary_data.loc[index, 'Total_Engineer_A'], style={'background-color': '#fbe9e7', 'font-weight': 'bold'}))
        
        rows.append(html.Tr(row_cells))
        
    return html.Div(
        html.Table([html.Thead(html.Tr(header)), html.Tbody(rows)]),
        style={'overflowX': 'scroll', 'maxHeight': '800px', 'overflowY': 'auto', 'width': '100%'}
    )


app.layout = html.Div(style={'backgroundColor': '#f9f9f9', 'padding': '20px'}, children=[
    
    html.H1("✅ Driver & Engineer Attendance Dashboard (Final)", 
            style={'textAlign': 'center', 'color': '#1f497d', 'marginBottom': '10px'}),
            
    html.P("Pivot Index: Circle और Vehicle | अंतिम कॉलम में Present और Absent Days का सारांश है।", 
           style={'textAlign': 'center', 'marginBottom': '30px'}),

    # Legend (कलर कोड)
    html.Div([
        html.Span("Legend:", style={'fontWeight': 'bold', 'marginRight': '10px'}),
        html.Span("P (Full Present)", style={'backgroundColor': COLOR_STYLE['P (Full Green)'].split(':')[1].split(';')[0], 'padding': '5px', 'marginRight': '15px', 'border': '1px solid black'}),
        html.Span("P (Vehicle Present, Eng. Absent)", style={'backgroundColor': COLOR_STYLE['P'].split(':')[1].split(';')[0], 'padding': '5px', 'marginRight': '15px', 'border': '1px solid black'}),
        html.Span("A (Any Absent Case)", style={'backgroundColor': COLOR_STYLE['A'].split(':')[1].split(';')[0], 'padding': '5px', 'border': '1px solid black'}),
    ], style={'textAlign': 'center', 'marginBottom': '20px'}),

    # कंबाइंड अटेंडेंस टेबल
    html.Div(style={'backgroundColor': 'white', 'padding': '20px', 'borderRadius': '8px'}, children=[
        html.H2(f"Combined Daily Status with Totals", 
                style={'color': '#007bff', 'borderBottom': '2px solid #007bff', 'paddingBottom': '5px'}),
        
        html.Div(id='combined-attendance-table', className='table-container')
    ]),
])


# --- 4. Callbacks (Table Generation) ---

@app.callback(Output('combined-attendance-table', 'children'),
              [Input('combined-attendance-table', 'id')])
def update_combined_table(id):
    return generate_styled_table(final_combined_pivot, summary_df, COLOR_STYLE)


# --- 5. App चलाएँ ---

if __name__ == '__main__':
    print("\n🚀 फाइनल डैशबोर्ड शुरू हो रहा है...")
    print("वेब ब्राउज़र में निम्नलिखित लिंक खोलें: http://127.0.0.1:8050/")
    app.run_server(debug=True)