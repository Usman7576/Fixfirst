import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { useState } from "react";
import { BrowserRouter, Route, Routes } from "react-router";

import { AuthProvider, RequireAuth } from "./auth/AuthProvider";
import { Layout } from "./components/Layout";
import { AuthCallbackPage } from "./pages/AuthCallbackPage";
import { ConnectRepoPage } from "./pages/ConnectRepoPage";
import { HomePage } from "./pages/HomePage";
import { LoginPage } from "./pages/LoginPage";

export function App() {
  const [queryClient] = useState(
    () => new QueryClient({ defaultOptions: { queries: { staleTime: 10_000, retry: 1 } } }),
  );

  return (
    <QueryClientProvider client={queryClient}>
      <BrowserRouter>
        <AuthProvider>
          <Routes>
            <Route path="/login" element={<LoginPage />} />
            <Route path="/auth/callback" element={<AuthCallbackPage />} />
            <Route
              element={
                <RequireAuth>
                  <Layout />
                </RequireAuth>
              }
            >
              <Route index element={<HomePage />} />
              <Route path="/repos/connect" element={<ConnectRepoPage />} />
            </Route>
          </Routes>
        </AuthProvider>
      </BrowserRouter>
    </QueryClientProvider>
  );
}
