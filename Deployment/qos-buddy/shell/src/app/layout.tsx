import type { Metadata, Viewport } from "next";
import "./globals.css";
import { AuthProvider } from "@/components/providers/auth-provider";
import { ThemeProvider } from "@/components/providers/theme-provider";
import { QueryProvider } from "@/components/providers/query-provider";
import { SocketProvider } from "@/components/providers/socket-provider";
import { AuthGate } from "@/components/auth-gate";
import { Sidebar } from "@/components/shell/sidebar";
import { Topbar } from "@/components/shell/topbar";
import { NotificationStack } from "@/components/ui/notifications";
import { ChatWidget } from "@/components/assistant/chat-widget";

export const metadata: Metadata = {
  title: "Qosmic — NOC Command Center",
  description: "Live network operations dashboard.",
};

export const viewport: Viewport = {
  themeColor: [
    { media: "(prefers-color-scheme: dark)", color: "#07101E" },
    { media: "(prefers-color-scheme: light)", color: "#F7F9FC" },
  ],
};

export default function RootLayout({
  children,
}: {
  children: React.ReactNode;
}) {
  return (
    <html lang="en" suppressHydrationWarning>
      <body className="font-sans">
        <AuthProvider>
          <ThemeProvider>
            <QueryProvider>
              <AuthGate>
                <SocketProvider>
                  <div className="flex min-h-screen bg-grad-cosmic">
                    <Sidebar />
                    <div className="flex min-w-0 flex-1 flex-col">
                      <Topbar />
                      <main className="container max-w-none flex-1 px-4 py-6 lg:px-6">
                        {children}
                      </main>
                      <NotificationStack />
                      <ChatWidget />
                    </div>
                  </div>
                </SocketProvider>
              </AuthGate>
            </QueryProvider>
          </ThemeProvider>
        </AuthProvider>
      </body>
    </html>
  );
}
