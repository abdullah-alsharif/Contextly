import type { Metadata } from "next";
import "./globals.css";

export const metadata: Metadata = {
  title: "Contextly",
  description:
    "Contextly — AI answers grounded in your documents, with sources you can verify.",
};

export default function RootLayout({
  children,
}: Readonly<{
  children: React.ReactNode;
}>) {
  return (
    <html lang="en">
      <body>{children}</body>
    </html>
  );
}