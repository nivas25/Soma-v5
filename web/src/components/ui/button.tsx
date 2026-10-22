import { Slot } from "@radix-ui/react-slot"
import { cva, type VariantProps } from "class-variance-authority"
import * as React from "react"

import { cn } from "@/lib/utils"

const buttonVariants = cva(
  "inline-flex items-center justify-center border-0 text-sm font-bold whitespace-nowrap transition-colors disabled:pointer-events-none disabled:opacity-40 outline-none",
  {
    variants: {
      variant: {
        default: "bg-[#094e43] text-white hover:bg-[#063830]",
        outline: "bg-neutral-100 text-neutral-800 hover:bg-neutral-200",
      },
      size: {
        default: "h-11 px-4",
        sm: "h-9 px-3",
      },
    },
    defaultVariants: { variant: "default", size: "default" },
  },
)

function Button({
  className,
  variant,
  size,
  asChild = false,
  ...props
}: React.ComponentProps<"button"> &
  VariantProps<typeof buttonVariants> & { asChild?: boolean }) {
  const Comp = asChild ? Slot : "button"
  return <Comp className={cn(buttonVariants({ variant, size, className }))} {...props} />
}

export { Button, buttonVariants }
