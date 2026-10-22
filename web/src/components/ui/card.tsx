import * as React from "react"

import { cn } from "@/lib/utils"

function Card({ className, ...props }: React.ComponentProps<"div">) {
  return <div className={cn("bg-white text-neutral-900 border-0 outline-none", className)} {...props} />
}

function CardHeader({ className, ...props }: React.ComponentProps<"div">) {
  return <div className={cn("px-5 py-4", className)} {...props} />
}

function CardTitle({ className, ...props }: React.ComponentProps<"h1">) {
  return <h1 className={cn("text-2xl font-bold tracking-tight", className)} {...props} />
}

function CardContent({ className, ...props }: React.ComponentProps<"div">) {
  return <div className={cn("px-5 py-5", className)} {...props} />
}

export { Card, CardContent, CardHeader, CardTitle }
