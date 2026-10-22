import { cva, type VariantProps } from "class-variance-authority"
import * as React from "react"

import { cn } from "@/lib/utils"

const badgeVariants = cva("inline-flex items-center rounded-full px-2.5 py-0.5 text-xs font-bold tracking-widest border-0", {
  variants: {
    variant: {
      speak: "bg-[#094e43] text-white",
      silent: "bg-neutral-100 text-neutral-800",
    },
  },
  defaultVariants: { variant: "silent" },
})

function Badge({
  className,
  variant,
  ...props
}: React.ComponentProps<"span"> & VariantProps<typeof badgeVariants>) {
  return <span className={cn(badgeVariants({ variant, className }))} {...props} />
}

export { Badge, badgeVariants }
