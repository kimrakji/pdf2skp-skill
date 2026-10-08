require 'json'
require 'digest'

module InteriorOS
  module WallExporter
    def self.points(ring)
      raise 'Invalid footprint ring' unless ring.is_a?(Array) && ring.length >= 3
      ring.map do |point|
        raise 'Invalid point' unless point.is_a?(Array) && point.length == 2
        raise 'Invalid coordinate' unless point.all? { |v| v.is_a?(Numeric) && v.finite? && v.abs <= 200_000 }
        Geom::Point3d.new(point[0].mm, point[1].mm, 0)
      end
    end

    def self.export(model_json_path, new_skp_path)
      raise 'Run inside SketchUp Desktop' unless defined?(Sketchup)
      payload = JSON.parse(File.read(model_json_path, encoding: 'UTF-8'))
      raise 'Unsupported model contract' unless payload['schema_version'] == '1.0' && payload['units'] == 'mm'
      raise 'Review is required before export' unless payload['status'] == 'ready_for_native_test' && payload['review_items'] == []
      raise 'Invalid model scope' unless %w[partial full_page].include?(payload['scope'])
      walls = payload.fetch('walls')
      raise 'No wall geometry' unless walls.is_a?(Array) && !walls.empty?
      path = File.expand_path(new_skp_path)
      raise 'Output must have .skp extension' unless File.extname(path).downcase == '.skp'
      report_path = path + '.validation.json'
      raise 'Output already exists' if File.exist?(path) || File.exist?(report_path)
      raise 'Output folder does not exist' unless File.directory?(File.dirname(path))
      model = Sketchup.active_model
      raise 'Use an empty model with no editing context' unless model.entities.length.zero? && model.active_path.nil?
      previous_layer = model.active_layer
      operation_started = false
      saved = false
      begin
        model.start_operation('Interior OS wall test', true)
        operation_started = true
        model.active_layer = model.layers[0]
        root = model.entities.add_group
        root.name = payload['scope'] == 'partial' ? 'InteriorOS_Partial_Test' : 'InteriorOS_Wall_Test'
        root.set_attribute('InteriorOS', 'geometry_sha256', payload.fetch('geometry_sha256'))
        root.set_attribute('InteriorOS', 'source_sha256', payload.fetch('source_sha256'))
        root.set_attribute('InteriorOS', 'scope', payload['scope'])
        groups = {}
        checks = walls.map do |wall|
          height = wall.fetch('height_mm')
          raise 'Invalid wall height' unless height.is_a?(Numeric) && height.finite? && height.between?(500, 10_000)
          area = wall.fetch('area_mm2')
          raise 'Invalid footprint area' unless area.is_a?(Numeric) && area.finite? && area > 0
          name = wall.fetch('group')
          raise 'Invalid group name' unless name.is_a?(String) && !name.empty?
          parent = groups[name] ||= root.entities.add_group
          parent.name = name
          parent.layer = model.layers[name] || model.layers.add(name)
          group = parent.entities.add_group
          group.name = wall.fetch('id')
          face = group.entities.add_face(points(wall.fetch('outer_mm')))
          raise "Cannot create face: #{group.name}" unless face && face.valid?
          wall.fetch('holes_mm').each do |hole|
            inner_face = group.entities.add_face(points(hole))
            raise 'Cannot create footprint hole' unless inner_face && inner_face.valid? && inner_face != face
            inner_face.erase!
          end
          raise 'Footprint face was lost' unless face.valid?
          face.reverse! if face.normal.z < 0
          face.pushpull(height.mm)
          raise "Wall is not a solid: #{group.name}" unless group.manifold?
          expected = area * height
          actual = group.volume.abs * (25.4 ** 3)
          error_ratio = (actual - expected).abs / expected
          raise "Wall volume differs: #{group.name}" if error_ratio > 0.001
          actual_height = (group.bounds.max.z - group.bounds.min.z).to_f * 25.4
          raise "Wall height differs: #{group.name}" if (actual_height - height).abs > 0.1
          group.set_attribute('InteriorOS', 'source_ids', wall.fetch('source_ids').join(','))
          {'id' => group.name, 'solid' => true, 'height_mm' => height, 'actual_height_mm' => actual_height,
           'expected_volume_mm3' => expected, 'actual_volume_mm3' => actual, 'volume_error_ratio' => error_ratio}
        end
        model.active_layer = previous_layer
        saved_ok = model.path.empty? ? model.save(path) : model.save_copy(path)
        raise 'SketchUp save failed' unless saved_ok
        saved = true
        model.commit_operation
        operation_started = false
        report = {'native_export' => 'saved_by_sketchup', 'sketchup_version' => Sketchup.version,
                  'skp_sha256' => Digest::SHA256.file(path).hexdigest,
                  'model_json_sha256' => Digest::SHA256.file(model_json_path).hexdigest,
                  'geometry_sha256' => payload['geometry_sha256'], 'scope' => payload['scope'],
                  'walls' => checks, 'reopen_verified' => false}
        File.open(report_path, 'wx', encoding: 'UTF-8') { |file| file.write(JSON.pretty_generate(report) + "\n") }
        {'skp_path' => path, 'validation_path' => report_path}
      rescue StandardError => error
        model.abort_operation if operation_started
        raise "#{error.message}#{saved ? ' (.skp saved; check the native report separately)' : ''}"
      ensure
        model.active_layer = previous_layer
      end
    end
  end
end
