import pandas as pd
import numpy as np
import logging
from scipy.signal import savgol_filter

def calculate_depth_eos80(p, lat):
    x = np.sin(np.deg2rad(lat))
    x = x * x
    gr = 9.780318 * (1.0 + (5.2788e-3 + 2.36e-5 * x) * x) + 1.092e-6 * p
    d = (((-1.82e-15 * p + 2.279e-10) * p - 2.2512e-5) * p + 9.72659) * p
    return d / gr

def calculate_theta_eos80(s, t, p, pr=0.0):
    def atg(s, t, p):
        ds = s - 35.0
        return ((((-2.1687e-16 * t + 1.8676e-14) * t - 4.6206e-13) * p + 
                 ((2.7759e-12 * t - 1.1351e-10) * ds + 
                 ((-5.4481e-14 * t + 8.733e-12) * t - 6.7795e-10) * t + 1.8741e-8)) * p + 
                 (-4.2393e-8 * t + 1.8932e-6) * ds + 
                 ((6.6228e-10 * t - 6.836e-8) * t + 8.5258e-6) * t + 3.5803e-5)
    h = pr - p
    xk = h * atg(s, t, p)
    t_step = t + 0.5 * xk
    q = xk
    p_step = p + 0.5 * h
    xk = h * atg(s, t_step, p_step)
    t_step += 0.29289322 * (xk - q)
    q = 0.58578644 * xk + 0.121320344 * q
    xk = h * atg(s, t_step, p_step)
    t_step += 1.707106781 * (xk - q)
    q = 3.414213562 * xk - 4.121320344 * q
    p_step = p + h
    xk = h * atg(s, t_step, p_step)
    return t_step + (xk - 2.0 * q) / 6.0

def calculate_density_eos80(s, t, p):
    A = [999.842594, 6.793952e-2, -9.095290e-3, 1.001685e-4, -1.120083e-6, 6.536332e-9]
    B = [8.24493e-1, -4.0899e-3, 7.6438e-5, -8.2467e-7, 5.3875e-9]
    C = [-5.72466e-3, 1.0227e-4, -1.6546e-6]
    D = [4.8314e-4]
    E = [19652.21, 148.4206, -2.327105, 1.360477e-2, -5.155288e-5]
    H = [3.239908, 1.43713e-3, 1.16092e-4, -5.77905e-7]
    K = [8.50935e-5, -6.12293e-6, 5.2787e-8]
    FQ = [54.6746, -0.603459, 1.09987e-2, -6.1670e-5]
    G = [7.944e-2, 1.6483e-2, -5.3009e-4]
    I = [2.2838e-3, -1.0981e-5, -1.6078e-6]
    J0 = 1.91075e-4
    M = [-9.9348e-7, 2.0816e-8, 9.1697e-10]
    
    s = np.maximum(s, 1e-6)
    p_bar = p / 10.0
    sigma = (A[0] + A[1]*t + A[2]*t**2 + A[3]*t**3 + A[4]*t**4 + A[5]*t**5 +
             (B[0] + B[1]*t + B[2]*t**2 + B[3]*t**3 + B[4]*t**4)*s +
             (C[0] + C[1]*t + C[2]*t**2)*s**1.5 + D[0]*s**2)
    kw = E[0] + E[1]*t + E[2]*t**2 + E[3]*t**3 + E[4]*t**4
    aw = H[0] + H[1]*t + H[2]*t**2 + H[3]*t**3
    bw = K[0] + K[1]*t + K[2]*t**2
    k = (kw + (FQ[0] + FQ[1]*t + FQ[2]*t**2 + FQ[3]*t**3)*s + (G[0] + G[1]*t + G[2]*t**2)*s**1.5 +
         (aw + (I[0] + I[1]*t + I[2]*t**2)*s + (J0*s**1.5))*p_bar +
         (bw + (M[0] + M[1]*t + M[2]*t**2)*s)*p_bar**2)
    return sigma / (1.0 - (p_bar / k))

def apply_soak_elimination(df, config):
    soak_depth = float(config.get('MIN_SAFE_PRESSURE', 5.0))
    min_velocity = float(config.get('LOOP_MIN_VELOCITY', 0.25))
    dp = df['pres_raw'].diff() * 4
    descent_mask = (df['pres_raw'] > soak_depth) & (dp > min_velocity)
    for i in range(len(descent_mask) - 20):
        if descent_mask.iloc[i:i+20].all():
            return df.loc[df.index[i]:].copy()
    return df[df['pres_raw'] > soak_depth].copy()

def apply_tau_shift(df, config):
    shift_steps = int(float(config.get('ALIGN_OXY_SHIFT', 5.0)))
    df['o2_final'] = df['o2_umol_l'].shift(-shift_steps).ffill()
    return df

def apply_ctm_correction(df, config):
    alpha = float(config.get('CTM_ALPHA', 0.04))
    tau = float(config.get('CTM_TAU', 8.0))
    df['cond_final'] = df['cond_raw'] / (1 + alpha * (np.exp(df['pres_raw'] / tau) - 1))
    return df

def apply_physics(df, config):
    t68_conv = float(config.get('T68_CONVERSION', 1.00024))
    win = int(config.get('AI_WINDOW', 15))
    poly = int(config.get('AI_POLY', 3))
    
    df['t68'] = df['temp_raw'] * t68_conv
    df['SP'] = df['sal_raw'] + float(config.get('SAL_OFFSET', 0.0))
    df['theta'] = df.apply(lambda r: calculate_theta_eos80(r['SP'], r['t68'], r['pres_raw']), axis=1)
    df['rho'] = calculate_density_eos80(df['SP'], df['t68'], df['pres_raw'])
    df['o2_final'] = (df['o2_umol_l'] * float(config.get('O2_BOOST_RATIO', 1.0))) / (df['rho'] / 1000.0)
    df['ph_final'] = df['ph_raw'] + float(config.get('PH_DRIFT', 0.0))
    df['chl_final'] = df['chl_raw']
    
    targets = ['rho', 'SP', 'theta', 'o2_final', 'ph_final']
    for col in targets:
        df[col] = df[col].interpolate(method='linear', limit_direction='both').fillna(0)
        df[col] = savgol_filter(df[col], win, poly)
    return df

def apply_surgical_chl(df, config):
    win = int(config.get('CHL_WINDOW', 5))
    poly = int(config.get('CHL_POLY', 2))
    roll = int(config.get('CHL_ROLL', 4))
    
    df['chl_final'] = df['chl_final'].interpolate(method='linear', limit_direction='both').fillna(0)
    df['chl_final'] = savgol_filter(df['chl_final'], win, poly)
    df['chl_final'] = df['chl_final'].rolling(window=roll, center=True).max().ffill().bfill()
    return df

def apply_qc_flags(df, config):
    threshold = float(config.get('QC_VELOCITY', 0.25))
    df['qc_flag'] = 3
    df.loc[df['pres_raw'].diff() * 4 >= threshold, 'qc_flag'] = 1
    return df
