-- public.quotation_requests
--
-- Website quotation form intake. NOT part of the CRM `crm` schema, so it is
-- deliberately outside Alembic: the website writes here through /api/quote
-- using the server-side Supabase secret key.
--
--   Website -> /api/quote -> Supabase secret key -> public.quotation_requests
--
-- The browser never writes to Supabase directly. RLS is enabled with no
-- policies at all, so anon/authenticated have no access; only the service role
-- (which bypasses RLS) can read or write.
--
-- No attachment columns and no Storage bucket: file/RFQ upload was removed.

create table public.quotation_requests (

  id uuid primary key default gen_random_uuid(),

  reference text not null unique
    default (
      'MPSTT-' ||
      to_char(
        now() at time zone 'Asia/Karachi',
        'YYYYMMDD'
      ) ||
      '-' ||
      upper(
        substr(
          replace(gen_random_uuid()::text, '-', ''),
          1,
          6
        )
      )
    ),

  full_name text not null
    check (char_length(full_name) between 1 and 100),

  organization text not null
    check (char_length(organization) between 1 and 150),

  phone text not null
    check (phone ~ '^\+?[0-9][0-9\s\-()]{6,19}$'),

  email text
    check (
      email is null
      or char_length(email) <= 150
    ),

  organization_type text
    check (
      organization_type is null
      or organization_type in (
        'Hospital',
        'Clinic',
        'Diagnostic',
        'Corporate',
        'Cleaning-FM',
        'Other'
      )
    ),

  requirement text not null
    check (
      char_length(requirement) between 10 and 5000
    ),

  consent boolean not null
    check (consent = true),

  source_page text
    check (
      source_page is null
      or char_length(source_page) <= 200
    ),

  product_slug text,

  category_slug text,

  product_name text,

  intent text
    check (
      intent is null
      or intent in ('quotation', 'other')
    ),

  status text not null default 'new'
    check (
      status in (
        'new',
        'contacted',
        'quotation_preparing',
        'quotation_sent',
        'won',
        'lost',
        'closed'
      )
    ),

  internal_notes text,

  contacted_at timestamptz,

  consent_at timestamptz
    not null default now(),

  created_at timestamptz
    not null default now(),

  updated_at timestamptz
    not null default now()
);

create index quotation_requests_created_at_idx
on public.quotation_requests (created_at desc);

create index quotation_requests_status_idx
on public.quotation_requests (status);

create or replace function public.set_quotation_requests_updated_at()
returns trigger
language plpgsql
as $$
begin
  new.updated_at = now();
  return new;
end;
$$;

create trigger quotation_requests_set_updated_at
before update on public.quotation_requests
for each row
execute function public.set_quotation_requests_updated_at();

alter table public.quotation_requests
enable row level security;
