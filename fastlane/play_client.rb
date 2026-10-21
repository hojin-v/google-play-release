require "supply"

class PlayReleaseRollout
  def self.options(value)
    fraction = Float(value)
    raise ArgumentError, "rollout must be greater than 0 and at most 1" unless fraction > 0 && fraction <= 1
    # Supply validates its configuration before converting this string to the API fraction.
    {release_status: fraction < 1 ? "inProgress" : "completed", rollout: fraction.to_s}
  end
end

# Use the pinned supply uploader, with app contact details and an explicit commit policy.
class PlayReleaseClient < Supply::Client
  attr_accessor :contact_email, :edit_status_path

  def commit_current_edit!
    ensure_active_edit!
    package = current_package_name
    edit_id = current_edit.id
    File.write(edit_status_path, JSON.pretty_generate(package_name: package, edit_id: edit_id) + "\n") if edit_status_path
    details = client.get_edit_detail(package, edit_id)
    if contact_email && details.contact_email != contact_email
      details.contact_email = contact_email
      client.update_edit_detail(package, edit_id, details)
    end
    begin
      client.commit_edit(package, edit_id,
                         changes_not_sent_for_review: Supply.config[:changes_not_sent_for_review],
                         changes_in_review_behavior: "ERROR_IF_IN_REVIEW")
    rescue Google::Apis::ClientError => error
      message = JSON.parse(error.body.to_s).dig("error", "message") rescue error.message
      raise unless error.status_code == 400 && message.include?("The query parameter changesNotSentForReview must not be set")

      FastlaneCore::UI.important("Google Play requires automatic review for these changes; committing the same edit without the review-hold parameter.")
      client.commit_edit(package, edit_id, changes_in_review_behavior: "ERROR_IF_IN_REVIEW")
    end
    self.current_edit = nil
    self.current_package_name = nil
    FastlaneCore::UI.success("Play changes and contact email saved (approval/publication are separate)")
  rescue Google::Apis::Error => error
    message = JSON.parse(error.body.to_s).dig("error", "message") rescue error.message
    raise error.class.new("Google Play HTTP #{error.status_code}: #{message}",
                          status_code: error.status_code, body: error.body)
  end
end

# Read committed track/artifact/image state and always discard the temporary read edit.
# A completed track release is not evidence of review approval or public availability.
class PlayReleaseSnapshot
  def self.read(service, package)
    edit = service.insert_edit(package)
    begin
      tracks = (service.list_edit_tracks(package, edit.id).tracks || []).map do |track|
        {track: track.track, releases: (track.releases || []).map { |r|
          {name: r.name, version_codes: r.version_codes, status: r.status, user_fraction: r.user_fraction}
        }}
      end
      bundles = (service.list_edit_bundles(package, edit.id).bundles || []).map { |b|
        {version_code: b.version_code, sha256: b.sha256}
      }
      countries = service.get_edit_countryavailability(package, edit.id, "production")
      images = (service.list_edit_listings(package, edit.id).listings || []).to_h do |listing|
        entries = service.list_edit_images(package, edit.id, listing.language, "phoneScreenshots").images || []
        [listing.language, entries.map { |image| {id: image.id, sha256: image.sha256, url: image.url} }]
      end
      {package_name: package, tracks: tracks, bundles: bundles, phone_screenshots: images,
       countries: (countries.countries || []).map(&:country_code), rest_of_world: countries.rest_of_world,
       note: "Committed API state; review approval and public availability require separate verification"}
    ensure
      service.delete_edit(package, edit.id)
    end
  end
end

class PlayReleaseUploader < Supply::Uploader
  attr_accessor :contact_email

  private

  def client
    @client ||= PlayReleaseClient.make_from_config
    @client.contact_email = contact_email
    @client.edit_status_path = File.join(ENV.fetch("PLAY_PROJECT_ROOT", Dir.pwd), "build/play-edit-status.json")
    @client
  end
end
