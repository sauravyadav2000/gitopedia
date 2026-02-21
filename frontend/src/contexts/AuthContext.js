import { createContext, useContext, useState, useEffect, useCallback } from 'react';
import { auth } from '@/lib/firebase';
import { onAuthStateChanged, signOut } from 'firebase/auth';

const API = process.env.REACT_APP_BACKEND_URL;
const AuthContext = createContext(null);

export function AuthProvider({ children }) {
  const [user, setUser] = useState(null);
  const [profile, setProfile] = useState(null);
  const [loading, setLoading] = useState(true);

  const refreshProfile = useCallback(async (firebaseUser) => {
    const target = firebaseUser || user;
    if (!target) return;
    try {
      const token = await target.getIdToken();
      const res = await fetch(`${API}/api/user/profile`, {
        headers: { Authorization: `Bearer ${token}` },
      });
      if (res.ok) {
        setProfile(await res.json());
      }
    } catch (e) {
      console.error('Failed to refresh profile', e);
    }
  }, [user]);

  useEffect(() => {
    return onAuthStateChanged(auth, async (firebaseUser) => {
      if (firebaseUser) {
        setUser(firebaseUser);
        try {
          const token = await firebaseUser.getIdToken();
          const res = await fetch(`${API}/api/auth/verify`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ token }),
          });
          if (res.ok) {
            setProfile(await res.json());
          }
        } catch (e) {
          console.error('Auth verify failed', e);
        }
      } else {
        setUser(null);
        setProfile(null);
      }
      setLoading(false);
    });
  }, []);

  const logout = () => signOut(auth);

  const getToken = async () => {
    if (user) return user.getIdToken();
    return null;
  };

  return (
    <AuthContext.Provider value={{ user, profile, loading, logout, getToken, refreshProfile }}>
      {children}
    </AuthContext.Provider>
  );
}

export const useAuth = () => useContext(AuthContext);
